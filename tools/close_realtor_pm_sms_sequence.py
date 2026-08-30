"""
Close CRM — Create Realtor / Property Manager SMS Outreach Sequence

Companion to close_realtor_pm_sequence.py (email version). Targets the
same Property Management / Real Estate Agency audience, but leads who
have a phone number on file and NO email — SMS is their only reachable
channel. Same 3-touch structure and offer (25% off first cleaning),
condensed for text.

Uses the verified, SMS-enabled Close-connected number: 786-838-4148
("Scrub Squad" line, phon_xgd6017OcW4UHTlmpQeZmvRvCCUkkf3zQlYVgvKfISD).
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

PHONE_NUMBER_ID = "phon_xgd6017OcW4UHTlmpQeZmvRvCCUkkf3zQlYVgvKfISD"  # 786-838-4148, "Scrub Squad" line


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

    print("Creating SMS templates for Realtor / Property Manager sequence...\n")

    sms1 = (
        'Hi {{ contact.first_name | default:"there" }}, this is Sentel with '
        "Scrub Squad. We handle move-in/move-out & tenant turnover cleaning "
        "for property managers/realtors in Miami-Dade, Homestead & the Keys "
        "- fast turnaround, no delays to your schedule. 25% off your first "
        "cleaning if you'd like to try us. Interested? Reply here or call/"
        "text 786-838-4148."
    )
    t1 = api_post("sms_template/", {"name": "Realtor-PM SMS | Step 1 - Initial Outreach", "text": sms1, "is_shared": True})
    print(f"  Template: {t1['name']} ({len(sms1)} chars)")

    sms2 = (
        'Hi {{ contact.first_name | default:"there" }}, following up - if a '
        "turnover or move-in/move-out cleaning ever comes up, keep Scrub "
        "Squad in mind. Reliable, on-time, checklist-based cleaning. 25% off "
        "your first one. Text 786-838-4148 anytime."
    )
    t2 = api_post("sms_template/", {"name": "Realtor-PM SMS | Step 2 - Follow-Up", "text": sms2, "is_shared": True})
    print(f"  Template: {t2['name']} ({len(sms2)} chars)")

    print("\nCreating: Realtor & Property Manager SMS Outreach...")
    seq = api_post("sequence/", {
        "name": "Realtor & Property Manager SMS Outreach",
        "sender_phone_number_id": PHONE_NUMBER_ID,
        "status": "paused",
        "timezone": "America/New_York",
        "steps": [
            {"delay": 0, "step_type": "sms", "sms_template_id": t1["id"]},
            {"delay": DAY * 5, "step_type": "sms", "sms_template_id": t2["id"]},
        ]
    })
    print(f"  Created: {seq['name']} ({seq['id']}) - 2 texts over 5 days")

    print("\n" + "=" * 60)
    print("SMS SEQUENCE CREATED (paused — review in Close before activating)")
    print("=" * 60)
    print(f"  {seq['name']} — {seq['id']}")
    print("  Sender number: 786-838-4148")
    print("\nGo to Close > Workflows to review, then activate when ready.")

    with open(os.path.join(os.path.dirname(__file__), "..", ".tmp", "realtor_pm_sms_sequence.json"), "w") as f:
        json.dump({"sequence_id": seq["id"], "template_ids": [t1["id"], t2["id"]]}, f, indent=2)


if __name__ == "__main__":
    main()
