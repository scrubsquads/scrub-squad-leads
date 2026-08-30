"""
Close CRM — Create Real Estate Agency/Realtor Outreach Sequence (Email)

Separate campaign from Property Management — same 25% first-clean offer
and company number, but the pitch leans on pre-listing/pre-showing
cleaning and making properties show well, not tenant turnover.
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

SENDER_ACCOUNT_ID = "emailacct_i5aPIJxDiZGPxJwhryabdcpSE5dCsWW7iymdxKhFyH8"
SENDER_NAME = "Sentel Mays"
SENDER_EMAIL = "sentelmays@scrubsquads.com"
SIGNATURE_PHONE = "786-838-4148"


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

    print("Creating templates for Real Estate Agency/Realtor sequence...\n")

    t1_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        "I'm Sentel with Scrub Squad — we clean properties for realtors and "
        "agencies across Miami-Dade, Homestead, and the Keys: pre-listing "
        "deep cleans, pre-showing touch-ups, and post-closing moves.<br><br>"
        "A clean, show-ready property closes faster — that's the whole "
        "reason we exist. What that means for you:<br><br>"
        "- Fast scheduling around your listing timeline, including short "
        "notice for last-minute showings<br>"
        "- Consistent, checklist-based cleaning so every property looks the "
        "same way, every time<br>"
        "- Direct communication — a real person to reach, not a call "
        "center<br><br>"
        "Happy to offer 25% off your first cleaning so you can see the "
        "quality for yourself, no obligation after that.<br><br>"
        f"Reply here or call/text me directly at {SIGNATURE_PHONE}.<br><br>"
        "Thanks,<br>Sentel<br>Scrub Squad"
    )
    t1 = api_post("email_template/", {
        "name": "RealEstate | Step 1 - Initial Outreach",
        "subject": "Show-ready cleaning for {{ lead.name }}'s listings",
        "body": t1_body,
        "is_shared": True
    })
    print(f"  Template: {t1['name']}")

    t2_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        "Just following up on my note about cleaning for {{ lead.name }}'s "
        "listings.<br><br>"
        "I know a messy or dusty showing can cost a sale before a buyer "
        "even gets past the front door. That's the #1 thing we solve — "
        "a property that's genuinely ready to show, on your schedule, not "
        "ours.<br><br>"
        "If you've got a listing coming up that could use a pre-showing or "
        "pre-listing clean, I'd be glad to quote it — no obligation.<br><br>"
        f"Reply here or reach me at {SIGNATURE_PHONE}.<br><br>"
        "Best,<br>Sentel<br>Scrub Squad"
    )
    t2 = api_post("email_template/", {
        "name": "RealEstate | Step 2 - Follow-Up",
        "subject": "Re: Show-ready cleaning for {{ lead.name }}",
        "body": t2_body,
        "is_shared": True
    })
    print(f"  Template: {t2['name']}")

    t3_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        "Last note from me — don't want to clutter your inbox. If a "
        "pre-listing or pre-showing cleaning ever comes up for "
        "{{ lead.name }}, keep Scrub Squad in mind. First cleaning is "
        "25% off, no risk in trying us.<br><br>"
        f"Reach me anytime at {SIGNATURE_PHONE} — no pressure either "
        "way.<br><br>"
        "Best,<br>Sentel<br>Scrub Squad"
    )
    t3 = api_post("email_template/", {
        "name": "RealEstate | Step 3 - Low-Pressure Close",
        "subject": "Keeping Scrub Squad in your back pocket",
        "body": t3_body,
        "is_shared": True
    })
    print(f"  Template: {t3['name']}")

    print("\nCreating: Real Estate Agency Outreach...")
    seq = api_post("sequence/", {
        "name": "Real Estate Agency Outreach",
        "sender_account_id": SENDER_ACCOUNT_ID,
        "sender_name": SENDER_NAME,
        "sender_email": SENDER_EMAIL,
        "status": "paused",
        "timezone": "America/New_York",
        "steps": [
            {"delay": 0, "step_type": "email", "email_template_id": t1["id"], "threading": "new_thread"},
            {"delay": DAY * 4, "step_type": "email", "email_template_id": t2["id"], "threading": "old_thread"},
            {"delay": DAY * 7, "step_type": "email", "email_template_id": t3["id"], "threading": "old_thread"},
        ]
    })
    print(f"  Created: {seq['name']} ({seq['id']}) - 3 emails over 11 days")

    with open(os.path.join(os.path.dirname(__file__), "..", ".tmp", "real_estate_sequence.json"), "w") as f:
        json.dump({"sequence_id": seq["id"], "template_ids": [t1["id"], t2["id"], t3["id"]]}, f, indent=2)

    print("\nDONE. Sequence created PAUSED — review in Close > Workflows > Archived before activating.")


if __name__ == "__main__":
    main()
