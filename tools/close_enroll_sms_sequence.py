"""
Enrol EXISTING Close leads into their industry SMS sequence, in bounded batches.

WHY THIS EXISTS
---------------
6 industry-specific SMS sequences exist (Commercial/Construction/Healthcare/
Real Estate/Realtor-PM/Warehouse), but only ~180 leads across ALL of them are
enrolled. Most "New Lead" / "Attempting Contact" leads have a phone number
but no email (Apollo enrichment coverage is near-zero for small South Florida
businesses), so the email-only close_enroll_sequence.py never reaches them.
SMS sequence_subscription needs no sender email, just lead_id + contact_id,
so phone-only leads can be enrolled here instead of sitting outside every
campaign indefinitely.

SCREENS (same as close_enroll_sequence.py, adapted for phone)
---------------------------------------------------------------
  - contact must have a phone number
  - number must be a South Florida area code (unless --allow-out-of-area)
  - lead status must be an outreach status (never Do Not Contact, Not
    Interested, Customer, Under Contract, In-House)
  - bad-fit blacklist from close_classify_new_leads
  - protected list from configs/do_not_email.txt
  - skips anyone already subscribed (any status) to ANY sequence for that
    lead - matches close_enroll_sequence.py's "already engaged" protection,
    applied lead-wide not just for the target sequence, so a lead who
    replied on the email sequence doesn't also get cold SMS'd

USAGE
    py tools/close_enroll_sms_sequence.py --list
    py tools/close_enroll_sms_sequence.py --sequence "Commercial SMS Outreach"
    py tools/close_enroll_sms_sequence.py --sequence "..." --limit 100 --apply
    py tools/close_enroll_sms_sequence.py --all-industries --limit 100 --apply
"""
import argparse
import base64
import collections
import csv
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

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
from close_classify_new_leads import classify  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BASE = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(
    f"{os.environ.get('CLOSE_API_KEY', '')}:".encode()).decode()

OUTREACH_STATUSES = {"New Lead", "Attempting Contact", "Contacted",
                     "Follow Up", "Hot Lead"}
SOUTH_FL = {"305", "786", "954", "561", "754"}
TOLLFREE_PREFIXES = {"800", "888", "877", "866", "855", "844", "833", "822"}

# Industry value (Close custom field) -> SMS sequence name
SMS_SEQ_BY_INDUSTRY = {
    "Property Management": "Realtor & Property Manager SMS Outreach",
    "Apartment Building": "Realtor & Property Manager SMS Outreach",
    "Real Estate": "Real Estate Agency SMS Outreach",
    "Construction": "Construction SMS Outreach",
    "Healthcare": "Healthcare SMS Outreach",
    "Warehouse": "Warehouse SMS Outreach",
}
SMS_COMMERCIAL_CATCHALL = "Commercial SMS Outreach"


def load_protected():
    path = Path(__file__).resolve().parent.parent / "configs" / "do_not_email.txt"
    if not path.exists():
        logger.warning("No configs/do_not_email.txt - protection list is EMPTY")
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line.lower())
    return out


PROTECTED = load_protected()


def call(path, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE}/{path}", data=data, method=method,
        headers={"Authorization": AUTH, "Accept": "application/json",
                 "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{e.code} {method} {path}: {e.read().decode()[:300]}")
    raise RuntimeError("retries exhausted")


def normalize_phone(raw):
    d = "".join(c for c in str(raw or "") if c.isdigit())
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) != 10:
        return None
    if d[:3] in TOLLFREE_PREFIXES:
        return None
    return d


def pick_phone_and_contact(lead):
    ranked = []
    for c in lead.get("contacts", []):
        for p in c.get("phones", []):
            num = normalize_phone(p.get("phone"))
            if not num:
                continue
            ptype = (p.get("type") or "").lower()
            rank = {"mobile": 0, "direct": 1}.get(ptype, 2)
            ranked.append((rank, num, c))
    if not ranked:
        return None, None
    ranked.sort(key=lambda x: x[0])
    _, num, contact = ranked[0]
    return num, contact


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="List SMS sequences and exit.")
    ap.add_argument("--sequence", help="SMS sequence name (or id).")
    ap.add_argument("--all-industries", action="store_true",
                    help="Enroll every eligible lead into its matching industry "
                         "SMS sequence in one run, instead of one sequence at a time.")
    ap.add_argument("--limit", type=int, default=100,
                    help="Max enrolments THIS RUN, per sequence. Default 100.")
    ap.add_argument("--status", default=None, help="Only leads in this exact status.")
    ap.add_argument("--allow-out-of-area", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="Actually enrol. Without this it is a preview.")
    ap.add_argument("--out", default=".tmp/sms_enrollment_plan.csv")
    args = ap.parse_args()

    sequences = call("sequence/")["data"]
    sms_sequences = {s["name"]: s for s in sequences if "SMS" in s["name"]}

    if args.list:
        logger.info("SMS sequences in this org:")
        for name, s in sms_sequences.items():
            logger.info("  %-42s id=%s", name, s["id"])
        return 0

    if not args.sequence and not args.all_industries:
        logger.info("Pass --sequence \"<name>\" or --all-industries. Use --list to see options.")
        return 0

    cfs = {f["name"]: f["id"] for f in call("custom_field/lead/")["data"]}
    ind_key = f"custom.{cfs['Industry']}" if "Industry" in cfs else None

    # Any active/goal/finished/paused subscription (on ANY sequence, email or
    # SMS) blocks re-enrollment - a lead already talking to us on email
    # should not also get cold-SMS'd, and vice versa.
    BLOCKING = {"active", "goal", "finished", "paused"}
    blocked_leads = set()
    for s in sequences:
        res = call(f"sequence_subscription/?sequence_id={s['id']}")
        for sub in res.get("data", []):
            if sub.get("status") in BLOCKING and sub.get("lead_id"):
                blocked_leads.add(sub["lead_id"])
    logger.info("Already sequenced (any sequence, non-error): %d leads", len(blocked_leads))

    logger.info("\nLoading leads...")
    leads, skip = [], 0
    while True:
        res = call(f"lead/?_limit=100&_skip={skip}")
        leads.extend(res["data"])
        if not res.get("has_more"):
            break
        skip += 100
    logger.info("  %d leads", len(leads))

    drop = collections.Counter()
    by_sequence = collections.defaultdict(list)

    for lead in leads:
        name = lead.get("display_name") or ""
        status = lead.get("status_label", "")

        if lead["id"] in blocked_leads:
            drop["already sequenced"] += 1
            continue
        if status not in OUTREACH_STATUSES:
            drop["status not eligible"] += 1
            continue
        if args.status and status != args.status:
            drop["status filter"] += 1
            continue

        blob = " ".join([
            name,
            " ".join((c.get("name") or "") for c in lead.get("contacts", [])),
        ]).lower()
        hit = next((p for p in PROTECTED if p in blob), None)
        if hit:
            drop[f"protected ({hit})"] += 1
            continue

        if "@" in name or "mail-tester" in name.lower():
            drop["junk record"] += 1
            continue

        verdict, reason = classify(name)
        if verdict == "DEFINITE_BAD":
            drop["bad fit"] += 1
            continue

        number, contact = pick_phone_and_contact(lead)
        if not number:
            drop["no usable phone"] += 1
            continue
        if not args.allow_out_of_area and number[:3] not in SOUTH_FL:
            drop["out of market"] += 1
            continue

        ind = (lead.get(ind_key) or "") if ind_key else ""
        target_seq_name = SMS_SEQ_BY_INDUSTRY.get(ind, SMS_COMMERCIAL_CATCHALL)

        if args.sequence:
            wanted = next((s for s in sms_sequences.values()
                          if s["name"].lower() == args.sequence.lower()
                          or s["id"] == args.sequence), None)
            if not wanted:
                logger.error("No SMS sequence matching %r", args.sequence)
                return 1
            if target_seq_name != wanted["name"]:
                drop["industry doesn't match --sequence"] += 1
                continue
            target_seq_name = wanted["name"]

        by_sequence[target_seq_name].append({
            "lead_id": lead["id"],
            "contact_id": contact["id"],
            "name": name,
            "status": status,
            "industry": ind or "(none - catchall)",
            "phone": number,
        })

    logger.info("\n%s", "=" * 64)
    logger.info("ENROLMENT PLAN (SMS)")
    logger.info("%s", "=" * 64)
    for k, v in drop.most_common():
        logger.info("  excluded - %-30s %5d", k, v)

    total_eligible = sum(len(v) for v in by_sequence.values())
    logger.info("  ELIGIBLE (all target sequences)   %5d", total_eligible)
    for seq_name, rows in sorted(by_sequence.items(), key=lambda x: -len(x[1])):
        logger.info("      %-42s %5d", seq_name, len(rows))

    all_batches = []
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_rows = []

    for seq_name, rows in by_sequence.items():
        seq = sms_sequences[seq_name]
        batch = rows[:args.limit]
        logger.info("\n  %s: this run --limit %d -> %d of %d eligible",
                    seq_name, args.limit, len(batch), len(rows))
        for c in batch:
            csv_rows.append({**c, "sequence": seq_name})
        all_batches.append((seq, batch))

    if csv_rows:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
            w.writeheader()
            w.writerows(csv_rows)
        logger.info("\n  plan file: %s", out_path)

    if not args.apply:
        logger.info("\nPREVIEW ONLY - nobody enrolled, no SMS sent.")
        return 0

    logger.info("\nEnrolling...")
    ok = fail = 0
    for seq, batch in all_batches:
        for c in batch:
            try:
                call("sequence_subscription/", "POST", {
                    "sequence_id": seq["id"],
                    "lead_id": c["lead_id"],
                    "contact_id": c["contact_id"],
                })
                ok += 1
                logger.info("  enrolled -> %-32s [%s]", c["name"][:32], seq["name"])
            except Exception as e:
                fail += 1
                logger.error("  FAILED   -> %-32s %s", c["name"][:32], e)
            time.sleep(0.3)

    logger.info("\n  enrolled: %d   failed: %d", ok, fail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
