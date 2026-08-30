"""
One-time retroactive recovery pass for the 17 leads fully suppressed by
close_suppress_bounces_and_stops.py BEFORE the recovery ladder existed.

For each: re-run the same recovery ladder (alt email on file -> website
scrape -> SMS fallback). If recovered, un-suppress: move the lead back to
its pre-suppression outreach status and re-enroll it in the SAME industry
sequence(s) it was in before (using close_migrate.py's classification
where possible, or Data Quality Flag -> "Clean" if using an alt/scraped
email). If NOT recovered, leave fully suppressed as-is (no change).

USAGE
    python retroactive_bounce_recovery.py            # dry run
    python retroactive_bounce_recovery.py --apply
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from close_suppress_bounces_and_stops import (  # noqa: E402
    attempt_bounce_recovery, close_call, DQ_FIELD,
)

STATE_PATH = Path(__file__).resolve().parent.parent / ".tmp" / "suppression_state.json"

# Sequences a recovered lead was almost certainly meant for — this is a
# best-effort re-enroll into the Commercial catch-all (safe default since
# most of the 17 came from the initial migration's Commercial bucket) via
# whichever channel (email/SMS) recovery produced. Sentel can manually
# re-route a specific one afterward if a different industry fits better.
COMMERCIAL_EMAIL_SEQ = "seq_3PIwJBhOUb3c3yyR45yOd7"
COMMERCIAL_SMS_SEQ = "seq_5LNhLRAPkoUm8BRMuFAZsA"
SENDER_ACCOUNT_ID = "emailacct_i5aPIJxDiZGPxJwhryabdcpSE5dCsWW7iymdxKhFyH8"
SENDER_NAME = "Sentel Mays"
SENDER_EMAIL = "sentelmays@scrubsquads.com"
PHONE_NUMBER_ID = "phon_xgd6017OcW4UHTlmpQeZmvRvCCUkkf3zQlYVgvKfISD"
NEW_LEAD_STATUS_ID = "stat_d857QdxZmTJKNUcl1XZMPcLgIG8BcQCylkQqiHstS2q"
CLEAN_CHOICE = "Clean"


def load_state():
    return json.loads(STATE_PATH.read_text())


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    state = load_state()
    bounced = {lid: info for lid, info in state["suppressed_leads"].items()
               if info["reason"] == "Bounced Email"}
    print(f"Retroactively checking {len(bounced)} previously-suppressed bounces...")

    recovered_count = failed_count = 0
    for lid, info in bounced.items():
        bad_email = info["detail"]
        lead = close_call(f"lead/{lid}/")
        contacts = lead.get("contacts", [])
        contact = next((c for c in contacts
                        if any(e.get("email", "").lower() == bad_email.lower() for e in c.get("emails", []))),
                       contacts[0] if contacts else None)
        if not contact:
            print(f"  {info['name']:40} SKIP (no contact record found)")
            failed_count += 1
            continue

        recovered, method, detail = attempt_bounce_recovery(
            lid, contact["id"], bad_email, dry_run=not args.apply, subs_index=None)

        if not recovered:
            print(f"  {info['name']:40} NOT RECOVERABLE (still suppressed)")
            failed_count += 1
            continue

        recovered_count += 1
        print(f"  {info['name']:40} RECOVERED via {method:18} -> {detail}")

        if args.apply:
            # Move back to New Lead + Clean, drop suppression state entry
            close_call(f"lead/{lid}/", "PUT", {"status_id": NEW_LEAD_STATUS_ID, DQ_FIELD: CLEAN_CHOICE})

            if method in ("alt_email_on_file", "website_scrape"):
                # Re-enroll in Commercial email (safe default) using the new/alt email
                try:
                    close_call("sequence_subscription/", "POST", {
                        "sequence_id": COMMERCIAL_EMAIL_SEQ,
                        "contact_id": contact["id"],
                        "sender_account_id": SENDER_ACCOUNT_ID,
                        "sender_name": SENDER_NAME,
                        "sender_email": SENDER_EMAIL,
                    })
                    print(f"      re-enrolled in Commercial Outreach (email)")
                except Exception as e:
                    print(f"      re-enroll FAILED: {e}")
                time.sleep(0.3)
            elif method == "sms_fallback":
                try:
                    close_call("sequence_subscription/", "POST", {
                        "sequence_id": COMMERCIAL_SMS_SEQ,
                        "contact_id": contact["id"],
                        "sender_phone_number_id": PHONE_NUMBER_ID,
                    })
                    print(f"      re-enrolled in Commercial SMS Outreach")
                except Exception as e:
                    print(f"      re-enroll FAILED: {e}")
                time.sleep(0.3)

            del state["suppressed_leads"][lid]
            state.setdefault("recovered_leads", {})[lid] = {
                "name": info["name"], "bad_email": bad_email, "method": method,
                "detail": detail, "retroactive": True,
            }

    if args.apply:
        save_state(state)
        print(f"\nDONE. Recovered: {recovered_count}  Still suppressed: {failed_count}")
    else:
        print(f"\nDRY RUN. Would recover: {recovered_count}  Would remain suppressed: {failed_count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
