"""
Harvest business email addresses from lead websites.

WHY
---
Apollo gives named decision-makers but costs a credit per email and the free
plan caps at 100 per billing cycle. Most small local businesses publish a
contact address right on their own site. This fills the `email` column in the
Leads tab for free, with no monthly ceiling, using the domains recovered by
backfill_websites.py.

Apollo and this are complementary: use credits for named contacts at
high-value accounts, use this for coverage.

WHAT COUNTS AS A HIT
--------------------
Only addresses that plausibly belong to the business:
  - same domain as the site (info@acmedrywall.com), or
  - a free-provider address published on the site (acme@gmail.com), which is
    extremely common for local trades

Rejected: template placeholders, CDN/platform noise (wixpress, sentry,
squarespace), image filenames that look like addresses (logo@2x.png), and
anything on a known vendor domain.

USAGE
    py tools/scrape_site_emails.py --dry-run
    py tools/scrape_site_emails.py --limit 50
    py tools/scrape_site_emails.py
"""
import argparse
import concurrent.futures
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists() and not os.environ.get("GITHUB_ACTIONS"):
    for _l in _env.read_text(encoding="utf-8").splitlines():
        _s = _l.strip()
        if _s and not _s.startswith("#") and "=" in _s:
            _k, _v = _s.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apollo import extract_domain  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

EMAIL_COL = 7          # 'email' is the 7th column in LEADS_HEADERS
TIMEOUT = 12
WORKERS = 8
FLUSH_EVERY = 40

CONTACT_PATHS = ["", "/contact", "/contact-us", "/contactus", "/about",
                 "/about-us", "/get-a-quote", "/quote"]

EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)
# "info (at) example (dot) com" style obfuscation
OBFUSCATED_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]+)\s*(?:\[at\]|\(at\)|\s+at\s+)\s*"
    r"([a-zA-Z0-9.\-]+)\s*(?:\[dot\]|\(dot\)|\s+dot\s+)\s*([a-zA-Z]{2,})",
    re.I,
)

FREE_PROVIDERS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "live.com", "msn.com", "comcast.net", "bellsouth.net",
    "att.net", "verizon.net", "me.com", "mac.com", "protonmail.com",
}

# Platform / vendor noise that appears in page source but is never the business
JUNK_DOMAINS = {
    "sentry.io", "sentry-next.wixpress.com", "wixpress.com", "wix.com",
    "squarespace.com", "godaddy.com", "example.com", "domain.com",
    "yourdomain.com", "email.com", "test.com", "sentry.wixpress.com",
    "w3.org", "schema.org", "googlemail.com", "cloudflare.com",
    "shopify.com", "wordpress.com", "weebly.com", "duda.co", "gostorego.com",
    "placeholder.com", "yoursite.com", "company.com", "business.com",
}
JUNK_LOCAL_PARTS = {
    "email", "your", "youremail", "name", "firstname", "someone", "user",
    "example", "test", "sample", "info@example", "no-reply", "noreply",
    "donotreply", "sentry",
}
IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp|bmp|ico|css|js)$", re.I)

# Ranked preference for role addresses
ROLE_PRIORITY = ["info", "contact", "office", "admin", "hello", "sales",
                 "estimating", "estimates", "service", "support", "inquiries"]


def clean_candidate(addr, site_domain):
    """Return a normalized address if it plausibly belongs to this business."""
    addr = addr.strip().strip(".,;:<>()[]\"'").lower()
    if "@" not in addr or IMAGE_EXT_RE.search(addr):
        return None
    local, _, dom = addr.rpartition("@")
    if not local or not dom or "." not in dom:
        return None
    if local in JUNK_LOCAL_PARTS or any(local.startswith(j) for j in ("your", "example")):
        return None
    if dom in JUNK_DOMAINS or any(dom.endswith("." + j) for j in JUNK_DOMAINS):
        return None
    # digits-only local parts are usually tracking ids
    if local.isdigit():
        return None
    if dom == site_domain or dom.endswith("." + site_domain) or dom in FREE_PROVIDERS:
        return addr
    # Some sites host mail on a sibling domain; accept if the root matches
    if site_domain and site_domain.split(".")[0] in dom:
        return addr
    return None


def rank(addr, site_domain):
    """Lower is better."""
    local, _, dom = addr.rpartition("@")
    same_domain = 0 if dom == site_domain or dom.endswith("." + site_domain) else 1
    try:
        role = ROLE_PRIORITY.index(local)
    except ValueError:
        role = len(ROLE_PRIORITY) + (0 if "@" in addr else 1)
    return (same_domain, role, len(addr))


def fetch(session, url):
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        ctype = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "text/html" in ctype:
            return r.text[:400_000]
    except Exception:
        pass
    return ""


def emails_for_site(website):
    """Return (best_email, all_found, pages_fetched)."""
    import requests

    site_domain = extract_domain(website) or ""
    if not site_domain:
        return "", [], 0

    base = website if website.startswith("http") else "https://" + website
    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (compatible; ScrubSquadLeadBot/1.0; "
                       "+contact via scrubsquads.com)"),
        "Accept": "text/html,application/xhtml+xml",
    })

    found, pages = set(), 0
    for path in CONTACT_PATHS:
        url = urljoin(base, path) if path else base
        html = fetch(session, url)
        if not html:
            continue
        pages += 1
        for m in EMAIL_RE.findall(html):
            c = clean_candidate(m, site_domain)
            if c:
                found.add(c)
        for a, b, c3 in OBFUSCATED_RE.findall(html):
            c = clean_candidate(f"{a}@{b}.{c3}", site_domain)
            if c:
                found.add(c)
        # Stop early once we have a same-domain role address
        if any(e.rpartition("@")[2] == site_domain
               and e.split("@")[0] in ROLE_PRIORITY for e in found):
            break

    if not found:
        return "", [], pages
    best = sorted(found, key=lambda e: rank(e, site_domain))[0]
    return best, sorted(found), pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Scrape and report, but write nothing to the sheet.")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--overwrite", action="store_true",
                    help="Re-scrape leads that already have an email.")
    args = ap.parse_args()

    import gspread
    sa = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    sh = gspread.service_account_from_dict(sa).open_by_key(os.environ["GOOGLE_SHEET_ID"])
    ws = sh.worksheet("Leads")
    records = ws.get_all_records()

    todo = []
    have_email = no_site = 0
    for i, r in enumerate(records):
        site = str(r.get("website", "")).strip()
        email = str(r.get("email", "")).strip()
        if not site:
            no_site += 1
            continue
        if email and not args.overwrite:
            have_email += 1
            continue
        todo.append((i + 2, site, r.get("business_name", "")))

    logger.info("Leads: %d", len(records))
    logger.info("  no website:        %d", no_site)
    logger.info("  already has email: %d", have_email)
    logger.info("  to scrape:         %d", len(todo))
    if args.limit:
        todo = todo[:args.limit]
        logger.info("  --limit -> %d this run", len(todo))
    if not todo:
        logger.info("Nothing to do.")
        return 0

    if args.dry_run:
        logger.info("\nDRY RUN — will scrape but not write. First 10 targets:")
        for row, site, name in todo[:10]:
            logger.info("  row %-5d %-38s %s", row, name[:38], site[:44])
        todo = todo[:10]

    results = {}
    done = 0
    logger.info("\nScraping %d sites with %d workers...", len(todo), WORKERS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(emails_for_site, site): (row, site, name)
                for row, site, name in todo}
        for fut in concurrent.futures.as_completed(futs):
            row, site, name = futs[fut]
            done += 1
            try:
                best, allf, pages = fut.result()
            except Exception as e:
                logger.warning("  %-34s ERROR %s", name[:34], type(e).__name__)
                continue
            if best:
                results[row] = best
                logger.info("  [%d/%d] %-32s %s", done, len(todo), name[:32], best)
            if done % 25 == 0:
                logger.info("  ...%d/%d scanned, %d emails found", done, len(todo), len(results))

    logger.info("\n%s", "=" * 62)
    logger.info("SCRAPE COMPLETE")
    logger.info("%s", "=" * 62)
    logger.info("  sites scanned:  %d", len(todo))
    logger.info("  emails found:   %d  (%.0f%%)", len(results),
                len(results) / len(todo) * 100)

    same_dom = sum(1 for r, e in results.items()
                   if e.rpartition("@")[2] not in FREE_PROVIDERS)
    logger.info("  on own domain:  %d", same_dom)
    logger.info("  free provider:  %d", len(results) - same_dom)

    if args.dry_run:
        logger.info("\nDRY RUN — nothing written.")
        return 0

    if results:
        import gspread.utils as gu
        items = sorted(results.items())
        for i in range(0, len(items), FLUSH_EVERY):
            chunk = items[i:i + FLUSH_EVERY]
            ws.batch_update([
                {"range": gu.rowcol_to_a1(row, EMAIL_COL), "values": [[email]]}
                for row, email in chunk
            ], value_input_option="RAW")
            logger.info("  wrote %d cells", len(chunk))
            time.sleep(1)
    logger.info("  done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
