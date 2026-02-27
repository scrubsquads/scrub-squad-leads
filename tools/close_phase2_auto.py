"""
Close CRM — Auto-Subscribe Finished Leads to Phase 2
Checks for contacts who completed Initial Outreach - Commercial
and subscribes them to Phase 2 - Commercial Follow-Up.

Run daily (e.g., via GitHub Actions or manually).
"""
import json
import time
import urllib.request
import urllib.error
import base64
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

API_KEY = os.environ.get("CLOSE_API_KEY", "")
BASE_URL = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(f"{API_KEY}:".encode()).decode()
SENDER = "emailacct_dFJqVFzngLhlf9T7g6lwJR8wo9F6wrgkEPZ0rfFJWDy"

# Source sequences (leads finish these)
SOURCE_SEQUENCES = {
    "Initial Outreach - Commercial": "seq_2Chrg4DReemWf9iAnu3i9R",
    "Initial Outreach - Education": "seq_4RJzLUfIitjgtjJus682KO",
}

# Destination
PHASE2_SEQ_ID = "seq_4ok6XNTiAYQuJzvBMfiPIb"


def api_get(path):
    req = urllib.request.Request(
        f"{BASE_URL}/{path}",
        headers={"Authorization": AUTH}
    )
    resp = urllib.request.urlopen(req)
    time.sleep(0.3)
    return json.loads(resp.read().decode())


def api_post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", data=body, method="POST",
        headers={"Authorization": AUTH, "Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        time.sleep(0.4)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"    ERROR {e.code}: {err[:300]}")
        return None


def get_all_subs(sequence_id, status=None):
    """Fetch all subscriptions for a sequence, optionally filtered by status."""
    subs = []
    offset = 0
    has_more = True
    while has_more:
        url = f"sequence_subscription/?sequence_id={sequence_id}&_limit=100&_skip={offset}"
        if status:
            url += f"&status={status}"
        data = api_get(url)
        subs.extend(data.get("data", []))
        has_more = data.get("has_more", False)
        offset += 100
    return subs


def main():
    if not API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        sys.exit(1)

    print("=" * 60)
    print("Phase 2 Auto-Subscribe")
    print("=" * 60)

    # 1. Get all contacts already in Phase 2 (any status) to avoid duplicates
    print("\nChecking existing Phase 2 subscriptions...")
    existing_phase2 = get_all_subs(PHASE2_SEQ_ID)
    already_in_phase2 = {sub["contact_id"] for sub in existing_phase2}
    print(f"  Already in Phase 2: {len(already_in_phase2)}")

    # 2. Get finished subscriptions from source sequences
    new_to_subscribe = []
    for name, seq_id in SOURCE_SEQUENCES.items():
        print(f"\nChecking finished contacts from: {name}...")
        finished = get_all_subs(seq_id, status="finished")
        print(f"  Finished: {len(finished)}")

        for sub in finished:
            contact_id = sub["contact_id"]
            if contact_id not in already_in_phase2:
                new_to_subscribe.append({
                    "contact_id": contact_id,
                    "lead_id": sub.get("lead_id", ""),
                    "source": name,
                })

    # Deduplicate by contact_id
    seen = set()
    unique = []
    for item in new_to_subscribe:
        if item["contact_id"] not in seen:
            seen.add(item["contact_id"])
            unique.append(item)
    new_to_subscribe = unique

    print(f"\nNew contacts to subscribe to Phase 2: {len(new_to_subscribe)}")

    if not new_to_subscribe:
        print("Nothing to do. All finished contacts are already in Phase 2.")
        return

    # 3. Subscribe them
    success = 0
    errors = 0
    for item in new_to_subscribe:
        result = api_post("sequence_subscription/", {
            "sequence_id": PHASE2_SEQ_ID,
            "contact_id": item["contact_id"],
            "sender_account_id": SENDER,
            "sender_name": "Christian",
            "sender_email": "christian@scrubsquads.com",
        })
        if result:
            success += 1
        else:
            errors += 1
            print(f"    Failed: {item['contact_id']}")

    print(f"\n{'=' * 60}")
    print(f"DONE: {success} subscribed to Phase 2, {errors} failed")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
