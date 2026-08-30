"""
Close CRM — Create Real Estate Agency/Realtor SMS Outreach Sequence

Companion to close_real_estate_sequence.py (email version). For leads with
a phone but no email. Uses the same verified SMS-enabled company number.
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

PHONE_NUMBER_ID = "phon_xgd6017OcW4UHTlmpQeZmvRvCCUkkf3zQlYVgvKfISD"  # 786-838-4148


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
        print(f"  ERROR {e.code}: {err[:500]}")
        raise


def main():
    if not API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        sys.exit(1)

    print("Creating SMS templates for Real Estate Agency sequence...\n")

    sms1 = (
        'Hi {{ contact.first_name | default:"there" }}, this is Sentel with '
        "Scrub Squad. We do pre-listing & pre-showing cleaning for realtors "
        "in Miami-Dade, Homestead & the Keys - fast turnaround, show-ready "
        "results. 25% off your first cleaning if you'd like to try us. "
        "Interested? Reply here or call/text 786-838-4148."
    )
    t1 = api_post("sms_template/", {"name": "RealEstate SMS | Step 1 - Initial Outreach", "text": sms1, "is_shared": True})
    print(f"  Template: {t1['name']} ({len(sms1)} chars)")

    sms2 = (
        'Hi {{ contact.first_name | default:"there" }}, following up - if a '
        "listing ever needs a pre-showing or pre-listing clean, keep Scrub "
        "Squad in mind. Show-ready, reliable, 25% off your first one. "
        "Text 786-838-4148 anytime."
    )
    t2 = api_post("sms_template/", {"name": "RealEstate SMS | Step 2 - Follow-Up", "text": sms2, "is_shared": True})
    print(f"  Template: {t2['name']} ({len(sms2)} chars)")

    print("\nCreating: Real Estate Agency SMS Outreach...")
    seq = api_post("sequence/", {
        "name": "Real Estate Agency SMS Outreach",
        "sender_phone_number_id": PHONE_NUMBER_ID,
        "status": "paused",
        "timezone": "America/New_York",
        "steps": [
            {"delay": 0, "step_type": "sms", "sms_template_id": t1["id"]},
            {"delay": DAY * 5, "step_type": "sms", "sms_template_id": t2["id"]},
        ]
    })
    print(f"  Created: {seq['name']} ({seq['id']}) - 2 texts over 5 days")

    with open(os.path.join(os.path.dirname(__file__), "..", ".tmp", "real_estate_sms_sequence.json"), "w") as f:
        json.dump({"sequence_id": seq["id"], "template_ids": [t1["id"], t2["id"]]}, f, indent=2)

    print("\nDONE. Sequence created PAUSED — review in Close > Workflows > Archived before activating.")


if __name__ == "__main__":
    main()
