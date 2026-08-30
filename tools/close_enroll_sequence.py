"""
Enrol EXISTING Close leads into an email sequence, in controlled batches.

WHY THIS EXISTS
---------------
close_sync.py only subscribes a lead at the moment it creates it. Once a lead
exists, re-running the sync skips it as a duplicate and never reaches the
subscription step. That left 527 leads with valid email addresses sitting in
Close, in active outreach statuses, never enrolled in anything - while seven
sequences sat active with zero subscriptions.

This tool is the other half: pick a sequence, pick a filter, enrol a bounded
batch. Run it repeatedly to ramp a cold domain instead of opening with
hundreds of messages in one day.

SCREENS (always on)
-------------------
  - contact must have an email address
  - lead status must be an outreach status (never Do Not Contact, Not
    Interested, Customer, Under Contract, In-House)
  - bad-fit blacklist from close_classify_new_leads
  - South Florida area codes only
  - skips anyone already subscribed to the target sequence

USAGE
    py tools/close_enroll_sequence.py --list
    py tools/close_enroll_sequence.py --sequence "Initial Outreach - Commercial"
    py tools/close_enroll_sequence.py --sequence "..." --limit 25 --apply
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


def load_protected():
    """Names/domains that must never receive outreach (current clients etc).

    Kept in configs/do_not_email.txt rather than in code so it can be edited
    without a deploy. Status alone is not enough protection: BHA Jewelry was a
    live client sitting in "Follow Up", which put it straight into the
    enrollable pool.
    """
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


def resolve_sender():
    for a in call("connected_account/").get("data", []):
        if "email_sending" in (a.get("enabled_features") or []):
            ident = a.get("default_identity") or {}
            return (a["id"], a.get("email", ""),
                    ident.get("name") or a.get("email", "").split("@")[0])
    raise RuntimeError("No connected account can send email.")


def area(phone):
    d = "".join(c for c in str(phone or "") if c.isdigit())
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d[:3] if len(d) == 10 else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="List sequences and exit.")
    ap.add_argument("--sequence", help="Sequence name (or id).")
    ap.add_argument("--limit", type=int, default=25,
                    help="Max enrolments this run. Default 25 - a cold domain "
                         "should ramp, not open at full volume.")
    ap.add_argument("--industry", default=None,
                    help="Only leads whose Industry custom field contains this.")
    ap.add_argument("--status", default=None,
                    help="Only leads in this exact status.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually enrol. Without this it is a preview.")
    ap.add_argument("--out", default=".tmp/enrollment_plan.csv")
    args = ap.parse_args()

    sequences = call("sequence/")["data"]
    if args.list or not args.sequence:
        logger.info("Sequences in this org:")
        for s in sequences:
            logger.info("  %-34s steps=%-2d status=%s  id=%s",
                        s["name"], len(s.get("steps", [])), s.get("status"), s["id"])
        if not args.sequence:
            logger.info("\nPass --sequence \"<name>\" to plan an enrolment.")
        return 0

    seq = next((s for s in sequences
                if s["name"].lower() == args.sequence.lower()
                or s["id"] == args.sequence), None)
    if not seq:
        logger.error("No sequence matching %r", args.sequence)
        return 1
    logger.info("Sequence: %s  (%d steps)", seq["name"], len(seq.get("steps", [])))

    acct_id, sender_email, sender_name = resolve_sender()
    logger.info("Sender:   %s <%s>", sender_name, sender_email)

    cfs = {f["name"]: f["id"] for f in call("custom_field/lead/")["data"]}
    ind_key = f"custom.{cfs['Industry']}" if "Industry" in cfs else None

    # Leads already in (or through) a sequence must not be re-enrolled.
    #
    # A reply sets the subscription to status "goal" with pause_reason
    # "reply-received" and stops the sequence - but the LEAD status stays
    # whatever it was. Florida Keys Realty replied within hours and was still
    # sitting in "New Lead", which put her straight back in the candidate pool.
    # Cold-introducing yourself to someone mid-conversation is worse than not
    # emailing at all.
    #
    # Errored subscriptions are deliberately NOT treated as blocking: 446 of
    # them failed on a dead sender account and never delivered anything, so
    # those contacts still need a real first touch.
    BLOCKING = {"active", "goal", "finished", "paused"}
    blocked_leads, blocked_contacts = set(), set()
    for s in sequences:
        res = call(f"sequence_subscription/?sequence_id={s['id']}")
        for sub in res.get("data", []):
            if sub.get("status") in BLOCKING:
                if sub.get("lead_id"):
                    blocked_leads.add(sub["lead_id"])
                if sub.get("contact_id"):
                    blocked_contacts.add(sub["contact_id"])
    logger.info("Already sequenced (any sequence, non-error): %d leads",
                len(blocked_leads))

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
    candidates = []
    for lead in leads:
        name = lead.get("display_name") or ""
        status = lead.get("status_label", "")

        if lead["id"] in blocked_leads:
            drop["already sequenced / replied"] += 1
            continue
        if status not in OUTREACH_STATUSES:
            drop["status not eligible"] += 1
            continue
        if args.status and status != args.status:
            drop["status filter"] += 1
            continue
        if args.industry:
            ind = (lead.get(ind_key) or "") if ind_key else ""
            if args.industry.lower() not in str(ind).lower():
                drop["industry filter"] += 1
                continue
        # Protected accounts: current clients and anyone who must never get
        # cold outreach. Checked against lead name, contact names and emails.
        blob = " ".join([
            name,
            " ".join((c.get("name") or "") for c in lead.get("contacts", [])),
            " ".join(e.get("email", "") for c in lead.get("contacts", [])
                     for e in (c.get("emails") or [])),
        ]).lower()
        hit = next((p for p in PROTECTED if p in blob), None)
        if hit:
            drop[f"protected ({hit})"] += 1
            continue

        # Junk records: the lead NAME is itself an email address, or it is a
        # deliverability test artifact. Six of these are sitting in the pool.
        if "@" in name or "mail-tester" in name.lower():
            drop["junk record"] += 1
            continue

        verdict, reason = classify(name)
        if verdict == "DEFINITE_BAD":
            drop["bad fit"] += 1
            continue

        acs = [area(p.get("phone")) for c in lead.get("contacts", [])
               for p in (c.get("phones") or [])]
        acs = [a for a in acs if a]
        if acs and not any(a in SOUTH_FL for a in acs):
            drop["out of market"] += 1
            continue

        contact = next((c for c in lead.get("contacts", []) if c.get("emails")), None)
        if not contact:
            drop["no email"] += 1
            continue

        candidates.append({
            "lead_id": lead["id"],
            "contact_id": contact["id"],
            "name": name,
            "status": status,
            "contact": contact.get("name") or "",
            "email": contact["emails"][0].get("email", ""),
        })

    # A cold intro sequence belongs to people who have not been contacted yet.
    # Someone in Follow Up has an open conversation; opening with "just an
    # introduction, no pitch" reads as if nobody is paying attention.
    COLD_FIRST = ["New Lead", "Attempting Contact"]
    ALREADY_ENGAGED = {"Contacted", "Follow Up", "Hot Lead"}
    order = {s: i for i, s in enumerate(COLD_FIRST)}
    candidates.sort(key=lambda c: (order.get(c["status"], 99), c["name"].lower()))

    engaged = [c for c in candidates if c["status"] in ALREADY_ENGAGED]

    logger.info("\n%s", "=" * 64)
    logger.info("ENROLMENT PLAN")
    logger.info("%s", "=" * 64)
    for k, v in drop.most_common():
        logger.info("  excluded - %-24s %5d", k, v)
    logger.info("  ELIGIBLE                       %5d", len(candidates))
    by_st = collections.Counter(c["status"] for c in candidates)
    for st, n in by_st.most_common():
        mark = "  <- already engaged" if st in ALREADY_ENGAGED else ""
        logger.info("      %-22s %5d%s", st, n, mark)

    if engaged and "initial outreach" in seq["name"].lower():
        logger.info("\n  WARNING: %d eligible leads are already in a conversation.",
                    len(engaged))
        logger.info("  They are sorted last so a --limit run reaches cold leads")
        logger.info("  first. Use --status \"New Lead\" to exclude them entirely.")

    batch = candidates[:args.limit]
    logger.info("  this run (--limit %d)           %5d", args.limit, len(batch))
    logger.info("  remaining after this run       %5d", len(candidates) - len(batch))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(batch[0].keys()) if batch else ["email"])
        w.writeheader()
        w.writerows(batch)
    logger.info("  plan file: %s", out)

    logger.info("\n  first %d to be enrolled:", min(10, len(batch)))
    for c in batch[:10]:
        logger.info("    %-34s %-22s %s", c["name"][:34], c["status"], c["email"][:34])

    if not args.apply:
        logger.info("\nPREVIEW ONLY - nobody enrolled, no email sent.")
        return 0

    logger.info("\nEnrolling %d contacts into %r...", len(batch), seq["name"])
    ok = fail = 0
    for c in batch:
        try:
            call("sequence_subscription/", "POST", {
                "sequence_id": seq["id"],
                "contact_id": c["contact_id"],
                "sender_account_id": acct_id,
                "sender_name": sender_name,
                "sender_email": sender_email,
            })
            ok += 1
            logger.info("  enrolled -> %-32s %s", c["name"][:32], c["email"][:34])
        except Exception as e:
            fail += 1
            logger.error("  FAILED   -> %-32s %s", c["name"][:32], e)
        time.sleep(0.5)

    logger.info("\n  enrolled: %d   failed: %d", ok, fail)
    logger.info("  still waiting: %d", len(candidates) - ok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
