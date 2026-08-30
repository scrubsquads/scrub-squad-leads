"""
Close CRM — Monthly Nudge Runner

Finds leads who FINISHED an original outreach sequence (email OR SMS, any
of the 7 industries) with no reply, and haven't been nudged in >= 30 days,
then sends them a fresh low-pressure nudge email via that industry's
dedicated nudge sequence (see close_build_nudge_sequences.py).

WHY DELETE + RECREATE EACH CYCLE:
Close refuses to re-subscribe a contact to a sequence they already have
ANY subscription record on, regardless of that record's status. So a
lead's PREVIOUS nudge subscription (status: finished, since the nudge
sequence is single-step) is deleted right before creating this month's
fresh one. That's why nudge sequences are single-step only — there's no
multi-step state to lose by deleting and recreating.

ELIGIBILITY (a lead qualifies for a nudge this run when ALL of):
  1. Lead status is still an outreach-eligible status (not Do Not Contact /
     Not Interested / In-House / Under Contract / Customer) — if the lead
     converted or was stopped, no nudge.
  2. Lead has a FINISHED (not active/error/goal) subscription on one of the
     7 original outreach sequences (email OR SMS) — "finished" means they
     went through the whole sequence with no reply/goal triggered.
  3. Lead has NEVER replied (no "goal" status subscription anywhere, and no
     inbound activity) — replies get worked personally, never automated.
  4. Lead was not already nudged in the last 30 days (tracked in
     .tmp/nudge_state.json, keyed by lead_id -> last_nudged ISO timestamp).

State file: .tmp/nudge_state.json — {lead_id: {"last_nudged": iso, "industry": str, "count": int}}

USAGE
    python close_monthly_nudge.py                 # dry run, prints plan
    python close_monthly_nudge.py --apply          # actually send nudges
    python close_monthly_nudge.py --apply --limit 50
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for _l in _env.read_text(encoding="utf-8").splitlines():
        _s = _l.strip()
        if _s and not _s.startswith("#") and "=" in _s:
            _k, _v = _s.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

API_KEY = os.environ.get("CLOSE_API_KEY", "")
BASE_URL = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(f"{API_KEY}:".encode()).decode()

SENDER_ACCOUNT_ID = "emailacct_i5aPIJxDiZGPxJwhryabdcpSE5dCsWW7iymdxKhFyH8"
SENDER_NAME = "Sentel Mays"
SENDER_EMAIL = "sentelmays@scrubsquads.com"

STATE_PATH = Path(__file__).resolve().parent.parent / ".tmp" / "nudge_state.json"
NUDGE_SEQ_PATH = Path(__file__).resolve().parent.parent / ".tmp" / "nudge_sequences.json"

# Original outreach sequences to watch for "finished, no reply" leads.
# email_seq / sms_seq may be None if that channel doesn't exist for the industry.
SOURCE_SEQUENCES = {
    "property_management": {"email": "seq_1cB6ULpeSvoD5rKt9o5Rzu", "sms": "seq_138WAOqUorf77ywDEencQo"},
    "real_estate": {"email": "seq_1kcWh8ObaVksKKZ1KL0Lns", "sms": "seq_3FI68L7PgjdUzWdw9AmCG0"},
    "construction": {"email": "seq_16UaJSNyYJlsaznOM9kPgD", "sms": "seq_7VvDV1wGKh1boZLdilM5SL"},
    "healthcare": {"email": "seq_1vnZAqssyuYviZI4byD4KU", "sms": "seq_44D9amOhMkCZAlzMm5QUKt"},
    "warehouse": {"email": "seq_1q2Gd2Ckaofo5ZtBOlFYqu", "sms": "seq_3x7OnSxdm1qDUy5Jb3J0tA"},
    "commercial": {"email": "seq_3PIwJBhOUb3c3yyR45yOd7", "sms": "seq_5LNhLRAPkoUm8BRMuFAZsA"},
    "education": {"email": "seq_4RJzLUfIitjgtjJus682KO", "sms": None},
}

OUTREACH_ELIGIBLE_STATUSES = {"New Lead", "Attempting Contact", "Contacted", "Follow Up", "Hot Lead"}
NUDGE_COOLDOWN_DAYS = 30


def close_call(path, method="GET", data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", data=body, method=method,
        headers={"Authorization": AUTH, "Accept": "application/json", "Content-Type": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as r:
                if r.status == 204:
                    return {}
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{e.code} {method} {path}: {e.read().decode()[:300]}")
    raise RuntimeError("retries exhausted")


def get_all_subs(sequence_id):
    """Fetch ALL subscriptions for a sequence. Close's status= query param is
    silently ignored (verified empirically), so status must always be
    filtered client-side on the returned 'status' field."""
    subs, skip = [], 0
    while True:
        res = close_call(f"sequence_subscription/?sequence_id={sequence_id}&_limit=200&_skip={skip}")
        subs.extend(res.get("data", []))
        if not res.get("has_more"):
            break
        skip += 200
    return subs


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def load_nudge_sequences():
    if not NUDGE_SEQ_PATH.exists():
        raise RuntimeError(f"{NUDGE_SEQ_PATH} not found — run close_build_nudge_sequences.py first")
    return json.loads(NUDGE_SEQ_PATH.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually send. Without this, dry run only.")
    ap.add_argument("--limit", type=int, default=None, help="Max nudges to send this run.")
    args = ap.parse_args()

    if not API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        return 1

    nudge_seqs = load_nudge_sequences()
    state = load_state()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=NUDGE_COOLDOWN_DAYS)

    # Step 1: find all lead_ids with a 'goal' (replied) subscription ANYWHERE
    # — these must never be nudged, regardless of which sequence they replied on.
    print("Scanning ALL sequences for any lead that has ever replied (status=goal)...")
    all_sequences = close_call("sequence/?_limit=200")["data"]
    replied_lead_ids = set()
    for s in all_sequences:
        for sub in get_all_subs(s["id"]):
            if sub.get("status") == "goal" and sub.get("lead_id"):
                replied_lead_ids.add(sub["lead_id"])
    print(f"  {len(replied_lead_ids)} leads have replied somewhere — excluded from nudges permanently.")

    # Step 2: for each industry's original outreach sequences, find FINISHED
    # subscriptions (went through, no reply) -> candidate leads.
    candidates = {}  # lead_id -> {"industry": str, "contact_id": str}
    for industry, seqs in SOURCE_SEQUENCES.items():
        for channel in ("email", "sms"):
            seq_id = seqs.get(channel)
            if not seq_id:
                continue
            for sub in get_all_subs(seq_id):
                if sub.get("status") != "finished":
                    continue
                lid = sub.get("lead_id")
                if not lid or lid in replied_lead_ids:
                    continue
                candidates.setdefault(lid, {"industry": industry, "contact_id": sub["contact_id"]})

    print(f"Finished-with-no-reply candidates across all industries: {len(candidates)}")

    # Step 3: filter by lead status (still outreach-eligible) + cooldown
    eligible = []
    for lid, info in candidates.items():
        last = state.get(lid, {}).get("last_nudged")
        if last:
            last_dt = datetime.fromisoformat(last)
            if last_dt > cutoff:
                continue  # nudged within the last 30 days
        try:
            lead = close_call(f"lead/{lid}/")
        except Exception as e:
            print(f"  WARN: could not fetch lead {lid}: {e}")
            continue
        if lead.get("status_label") not in OUTREACH_ELIGIBLE_STATUSES:
            continue
        eligible.append({
            "lead_id": lid,
            "contact_id": info["contact_id"],
            "industry": info["industry"],
            "name": lead.get("display_name"),
        })

    print(f"Eligible for a nudge THIS run (status ok + cooldown passed): {len(eligible)}")

    if args.limit:
        eligible = eligible[: args.limit]
        print(f"  Limited to {len(eligible)} by --limit")

    if not args.apply:
        print("\nDRY RUN. Nobody nudged. Sample of what would be sent:")
        for e in eligible[:15]:
            print(f"  {e['name']:40} industry={e['industry']}")
        if len(eligible) > 15:
            print(f"  ... and {len(eligible) - 15} more")
        return 0

    # Step 4: for each eligible lead, delete any PRIOR nudge subscription
    # (Close blocks re-subscribing while any record exists), then create
    # a fresh one on that industry's nudge sequence.
    sent = failed = 0
    for e in eligible:
        nudge_seq_id = nudge_seqs.get(e["industry"], {}).get("sequence_id")
        if not nudge_seq_id:
            print(f"  SKIP {e['name']}: no nudge sequence configured for {e['industry']}")
            continue
        try:
            # Delete any existing subscription this contact has on the nudge seq
            existing = [s for s in get_all_subs(nudge_seq_id) if s.get("contact_id") == e["contact_id"]]
            for s in existing:
                close_call(f"sequence_subscription/{s['id']}/", "DELETE")
                time.sleep(0.2)

            close_call("sequence_subscription/", "POST", {
                "sequence_id": nudge_seq_id,
                "contact_id": e["contact_id"],
                "sender_account_id": SENDER_ACCOUNT_ID,
                "sender_name": SENDER_NAME,
                "sender_email": SENDER_EMAIL,
            })
            sent += 1
            prior_count = state.get(e["lead_id"], {}).get("count", 0)
            state[e["lead_id"]] = {
                "last_nudged": now.isoformat(),
                "industry": e["industry"],
                "count": prior_count + 1,
            }
            print(f"  NUDGED: {e['name']} ({e['industry']}) — nudge #{prior_count + 1}")
        except Exception as ex:
            failed += 1
            print(f"  FAILED: {e['name']}: {ex}")
        time.sleep(0.3)

    save_state(state)
    print(f"\nDONE. sent={sent} failed={failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
