"""
Backfill the `website` column in the Leads tab from Google Places.

WHY THIS EXISTS
---------------
Every one of the leads in the sheet was scraped without a website captured,
so Apollo enrichment has been running on its weak company-name fallback path
and matching ~8% of the time. Apollo yields an email on 76% of the leads it
DOES match, so the bottleneck is domains, not Apollo.

Each lead carries a real Google Place ID, so the websites can be recovered
directly from Google without re-scraping and without Outscraper.

COST
----
Uses the legacy Place Details endpoint with a minimal field list:

  business_status -> Basic Data SKU   : free, unlimited
  website         -> Contact Data SKU : 1,000 events free per month,
                                        then $3.00 per 1,000

So a full pass over ~777 leads falls inside the free monthly allowance and
costs nothing. Cost only starts if total Contact Data calls in a calendar
month exceed 1,000 - e.g. re-running the whole sheet twice in one month.
--limit bounds the call count; --dry-run makes zero calls.

USAGE
-----
    py tools/backfill_websites.py --dry-run          # what would be looked up
    py tools/backfill_websites.py --limit 25         # spend-bounded trial
    py tools/backfill_websites.py                    # everything remaining
"""
import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists() and not os.environ.get("GITHUB_ACTIONS"):
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

MAPS_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# Keep the field list minimal - every extra field can add a billing SKU.
FIELDS = "website,business_status"

# Column position of `website` in LEADS_HEADERS (1-indexed for gspread).
# place_id, business_name, business_type, region, full_address, phone, email,
# website  -> 8th column = H
WEBSITE_COL = 8

INTER_CALL_DELAY = 0.05   # Places allows high QPS; this is politeness
FLUSH_EVERY = 50          # write partial results back this often


def place_details(place_id):
    """Return (website, business_status, error)."""
    q = urllib.parse.urlencode({
        "place_id": place_id,
        "fields": FIELDS,
        "key": MAPS_KEY,
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{DETAILS_URL}?{q}", timeout=45) as r:
                body = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if attempt == 2:
                return "", "", f"HTTP {e.code}"
            time.sleep(2 ** attempt)
        except Exception as e:
            if attempt == 2:
                return "", "", type(e).__name__
            time.sleep(2 ** attempt)
    else:
        return "", "", "retries exhausted"

    status = body.get("status")
    if status == "OK":
        res = body.get("result") or {}
        return (res.get("website") or "").strip(), res.get("business_status", ""), ""
    if status == "ZERO_RESULTS":
        return "", "", "ZERO_RESULTS"
    if status == "NOT_FOUND":
        return "", "", "NOT_FOUND"
    return "", "", f"{status}: {(body.get('error_message') or '')[:120]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would be looked up. Spends nothing.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Look up at most N leads. Bounds API spend.")
    ap.add_argument("--overwrite", action="store_true",
                    help="Re-look-up leads that already have a website.")
    args = ap.parse_args()

    if not MAPS_KEY:
        logger.error("GOOGLE_MAPS_API_KEY not set in .env")
        return 1
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        logger.error("GOOGLE_SERVICE_ACCOUNT_JSON not set in .env")
        return 1

    import gspread
    sa = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    sh = gspread.service_account_from_dict(sa).open_by_key(os.environ["GOOGLE_SHEET_ID"])
    ws = sh.worksheet("Leads")

    records = ws.get_all_records()
    logger.info("Leads tab: %d rows", len(records))

    # Row N in records maps to sheet row N + 2 (header is row 1).
    todo = []
    already = 0
    no_pid = 0
    for i, r in enumerate(records):
        pid = str(r.get("place_id", "")).strip()
        site = str(r.get("website", "")).strip()
        if not pid or pid.startswith("FALLBACK_"):
            no_pid += 1
            continue
        if site and not args.overwrite:
            already += 1
            continue
        todo.append((i + 2, pid, r.get("business_name", "")))

    logger.info("  already have a website: %d", already)
    logger.info("  unusable place_id:      %d", no_pid)
    logger.info("  to look up:             %d", len(todo))

    if args.limit:
        todo = todo[:args.limit]
        logger.info("  --limit %d applied -> %d this run", args.limit, len(todo))

    if not todo:
        logger.info("Nothing to do.")
        return 0

    # `website` is the only billable field requested (Contact Data SKU).
    # First 1,000 Contact Data events each calendar month are free.
    FREE_CONTACT_EVENTS = 1000
    RATE_PER_1000 = 3.00
    billable = max(0, len(todo) - FREE_CONTACT_EVENTS)
    cost = billable / 1000 * RATE_PER_1000
    logger.info("  billable Contact Data events: %d of %d "
                "(first %d/month are free)", billable, len(todo), FREE_CONTACT_EVENTS)
    logger.info("  estimated cost: $%.2f  %s", cost,
                "" if billable else "(within the free monthly allowance)")
    logger.info("  NOTE: assumes no other Contact Data calls yet this month.")

    if args.dry_run:
        logger.info("\nDRY RUN - no API calls, no sheet writes. First 10:")
        for row, pid, name in todo[:10]:
            logger.info("  row %-5d %-42s %s", row, name[:42], pid)
        return 0

    found = missing = errored = 0
    closed = []
    errors = {}
    pending = []   # (row, website)

    def flush():
        if not pending:
            return
        ws.batch_update([
            {"range": gspread.utils.rowcol_to_a1(row, WEBSITE_COL), "values": [[site]]}
            for row, site in pending
        ], value_input_option="RAW")
        logger.info("    ...wrote %d cells", len(pending))
        pending.clear()

    logger.info("\nLooking up %d places...", len(todo))
    for n, (row, pid, name) in enumerate(todo, 1):
        site, status, err = place_details(pid)
        if err:
            errored += 1
            errors[err] = errors.get(err, 0) + 1
        elif site:
            found += 1
            pending.append((row, site))
        else:
            missing += 1
        if status == "CLOSED_PERMANENTLY":
            closed.append(name)

        if n % FLUSH_EVERY == 0:
            logger.info("  %d/%d  (found %d, none %d, err %d)", n, len(todo), found, missing, errored)
            flush()
        time.sleep(INTER_CALL_DELAY)

    flush()

    logger.info("\n%s", "=" * 60)
    logger.info("BACKFILL COMPLETE")
    logger.info("%s", "=" * 60)
    logger.info("  looked up:        %d", len(todo))
    logger.info("  websites found:   %d  (%.0f%%)", found, found / len(todo) * 100)
    logger.info("  no website on listing: %d", missing)
    logger.info("  errors:           %d  %s", errored, errors or "")
    if closed:
        logger.info("\n  PERMANENTLY CLOSED businesses found: %d", len(closed))
        for c in closed[:15]:
            logger.info("    - %s", c)
        out = Path(".tmp/permanently_closed.txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(closed), encoding="utf-8")
        logger.info("  full list -> %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
