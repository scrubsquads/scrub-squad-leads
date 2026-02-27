"""
Close CRM — Create 3 New Email Sequences
1. Under Contract Nurture (3 emails over 90 days)
2. In-House Conversion (3 emails over 45 days)
3. Phase 2 Commercial Follow-Up (4 emails over 21 days)
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
DAY = 86400
SENDER = "emailacct_dFJqVFzngLhlf9T7g6lwJR8wo9F6wrgkEPZ0rfFJWDy"


def api_post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", data=body, method="POST",
        headers={"Authorization": AUTH, "Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        time.sleep(0.5)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  ERROR {e.code}: {err[:400]}")
        raise


def main():
    if not API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        sys.exit(1)

    # Load new template IDs from Step 2
    with open(".tmp/new_template_ids.json") as f:
        new_ids = json.load(f)

    # Existing template IDs for reuse
    WALKTHROUGH_TEMPLATE = "tmpl_hI5g7Ib4gQrZabd3N526JocpWhOvwYLwNzK50Oi1DLE"  # Commercial Step 4
    PHASE2_STEP1 = "tmpl_aHraJWP1O84rBe1bCtmDpYhW9eqh0sROgDQjkmq2N2X"  # #5
    PHASE2_STEP2 = "tmpl_m1TrO5fIx9UENXaPNcArs2NcQcCY8WBbxbgtbMJGalX"  # #7
    PHASE2_STEP3 = "tmpl_GmX2w4aVgi902fUUWpW2iCxBLeCbMGrCyqzjHl2EOXb"  # #8
    PHASE2_STEP4 = "tmpl_0brxO7eKluWmOc7GDYX5KtI3LvenCOii72B0sELoqGJ"  # #10

    # =================================================================
    # 1. Under Contract Nurture (3 emails over 90 days)
    # =================================================================
    print("Creating: Under Contract Nurture...")
    seq1 = api_post("sequence/", {
        "name": "Under Contract Nurture",
        "sender_account_id": SENDER,
        "sender_name": "Christian",
        "sender_email": "christian@scrubsquads.com",
        "status": "active",
        "timezone": "America/New_York",
        "steps": [
            {"delay": 0, "step_type": "email", "email_template_id": new_ids["under_contract_1"], "threading": "new_thread"},
            {"delay": DAY * 30, "step_type": "email", "email_template_id": new_ids["under_contract_2"], "threading": "old_thread"},
            {"delay": DAY * 30, "step_type": "email", "email_template_id": WALKTHROUGH_TEMPLATE, "threading": "old_thread"},
        ]
    })
    print(f"  Created: {seq1['name']} ({seq1['id']}) - 3 emails over 90 days")

    # =================================================================
    # 2. In-House Conversion (3 emails over 45 days)
    # =================================================================
    print("\nCreating: In-House Conversion...")
    seq2 = api_post("sequence/", {
        "name": "In-House Conversion",
        "sender_account_id": SENDER,
        "sender_name": "Christian",
        "sender_email": "christian@scrubsquads.com",
        "status": "active",
        "timezone": "America/New_York",
        "steps": [
            {"delay": 0, "step_type": "email", "email_template_id": new_ids["in_house_1"], "threading": "new_thread"},
            {"delay": DAY * 14, "step_type": "email", "email_template_id": new_ids["in_house_2"], "threading": "old_thread"},
            {"delay": DAY * 16, "step_type": "email", "email_template_id": WALKTHROUGH_TEMPLATE, "threading": "old_thread"},
        ]
    })
    print(f"  Created: {seq2['name']} ({seq2['id']}) - 3 emails over 45 days")

    # =================================================================
    # 3. Phase 2 Commercial Follow-Up (4 emails over 21 days)
    # =================================================================
    print("\nCreating: Phase 2 - Commercial Follow-Up...")
    seq3 = api_post("sequence/", {
        "name": "Phase 2 - Commercial Follow-Up",
        "sender_account_id": SENDER,
        "sender_name": "Christian",
        "sender_email": "christian@scrubsquads.com",
        "status": "active",
        "timezone": "America/New_York",
        "steps": [
            {"delay": 0, "step_type": "email", "email_template_id": PHASE2_STEP1, "threading": "new_thread"},
            {"delay": DAY * 7, "step_type": "email", "email_template_id": PHASE2_STEP2, "threading": "old_thread"},
            {"delay": DAY * 7, "step_type": "email", "email_template_id": PHASE2_STEP3, "threading": "old_thread"},
            {"delay": DAY * 7, "step_type": "email", "email_template_id": PHASE2_STEP4, "threading": "old_thread"},
        ]
    })
    print(f"  Created: {seq3['name']} ({seq3['id']}) - 4 emails over 21 days")

    # =================================================================
    # Summary
    # =================================================================
    print("\n" + "=" * 60)
    print("ALL NEW SEQUENCES CREATED (active)")
    print("=" * 60)
    print(f"  1. {seq1['name']} - 3 emails over 90 days ({seq1['id']})")
    print(f"  2. {seq2['name']} - 3 emails over 45 days ({seq2['id']})")
    print(f"  3. {seq3['name']} - 4 emails over 21 days ({seq3['id']})")

    # Save sequence IDs
    seq_ids = {
        "under_contract_nurture": seq1["id"],
        "in_house_conversion": seq2["id"],
        "phase2_commercial": seq3["id"],
    }
    with open(".tmp/new_sequence_ids.json", "w") as f:
        json.dump(seq_ids, f, indent=2)
    print("\n  Sequence IDs saved to .tmp/new_sequence_ids.json")


if __name__ == "__main__":
    main()
