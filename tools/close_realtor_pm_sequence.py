"""
Close CRM — Create Realtor / Property Manager Outreach Sequence

Targets: Property Management Companies + Real Estate Agencies (move-in/
move-out turnover cleanings, tenant/listing prep). Different pitch than
the general commercial sequence — speed/reliability and flexible
scheduling around tenant timelines are the hooks here, not generic
"we clean offices" messaging.

Uses the ACTUAL currently-connected Close send account
(sentelmays@scrubsquads.com) — the old christian@scrubsquads.com sender
used in earlier scripts no longer exists in this org.
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
SIGNATURE_PHONE = "786-838-4148"  # company number — use on ALL email communications, not personal cell


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

    print("Creating templates for Realtor / Property Manager sequence...\n")

    # =========================================
    # Step 1 — Initial outreach
    # =========================================
    t1_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        "I'm Sentel with Scrub Squad — we handle move-in/move-out and tenant "
        "turnover cleaning for property managers and realtors across "
        "Miami-Dade, Homestead, and the Keys.<br><br>"
        "A few things that make us easy to work with on tight turnaround "
        "timelines:<br><br>"
        "- Fast scheduling — we can usually work around your tenant move-out/"
        "move-in dates, not the other way around<br>"
        "- Consistent, checklist-based cleaning so every unit is handled the "
        "same way<br>"
        "- Direct communication — you'll always have a real person to reach, "
        "not a call center<br><br>"
        "If you manage properties or handle listings that need turnover or "
        "pre-showing cleaning, I'd love to be your go-to. "
        "Happy to offer 25% off your first cleaning so you can see the quality "
        "for yourself, no obligation after that.<br><br>"
        f"Reply here or call/text me directly at {SIGNATURE_PHONE}.<br><br>"
        "Thanks,<br>Sentel<br>Scrub Squad"
    )
    t1 = api_post("email_template/", {
        "name": "Realtor-PM | Step 1 - Initial Outreach",
        "subject": "Turnover cleaning for {{ lead.name }} — fast, reliable, flexible scheduling",
        "body": t1_body,
        "is_shared": True
    })
    print(f"  Template: {t1['name']}")

    # =========================================
    # Step 2 — Follow-up, reliability angle
    # =========================================
    t2_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        "Just following up on my note about turnover cleaning for "
        "{{ lead.name }}.<br><br>"
        "I know the biggest headache with cleaning vendors is reliability — "
        "a late or no-show cleaning can delay a move-in or a showing. "
        "That's the #1 thing we optimize for: showing up on time, every "
        "time, so your schedule never slips because of us.<br><br>"
        "If you've got a property coming up that needs a turnover clean, "
        "I'd be glad to quote it — no obligation.<br><br>"
        f"Reply here or reach me at {SIGNATURE_PHONE}.<br><br>"
        "Best,<br>Sentel<br>Scrub Squad"
    )
    t2 = api_post("email_template/", {
        "name": "Realtor-PM | Step 2 - Reliability Follow-Up",
        "subject": "Re: Turnover cleaning for {{ lead.name }}",
        "body": t2_body,
        "is_shared": True
    })
    print(f"  Template: {t2['name']}")

    # =========================================
    # Step 3 — Final, low-pressure close
    # =========================================
    t3_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        "Last note from me on this — I don't want to clutter your inbox. "
        "If a turnover or move-in/move-out cleaning need ever comes up for "
        "{{ lead.name }}, keep Scrub Squad in mind. First cleaning is "
        "discounted so there's no risk in trying us out.<br><br>"
        f"You can always reach me directly at {SIGNATURE_PHONE} whenever it's "
        "useful — no pressure either way.<br><br>"
        "Best,<br>Sentel<br>Scrub Squad"
    )
    t3 = api_post("email_template/", {
        "name": "Realtor-PM | Step 3 - Low-Pressure Close",
        "subject": "Keeping Scrub Squad in your back pocket",
        "body": t3_body,
        "is_shared": True
    })
    print(f"  Template: {t3['name']}")

    # =========================================
    # Build the sequence (paused — review before activating)
    # =========================================
    print("\nCreating: Realtor & Property Manager Outreach...")
    seq = api_post("sequence/", {
        "name": "Realtor & Property Manager Outreach",
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

    print("\n" + "=" * 60)
    print("SEQUENCE CREATED (paused — review in Close before activating)")
    print("=" * 60)
    print(f"  {seq['name']} — {seq['id']}")
    print("  Sender:", SENDER_EMAIL)
    print("\nGo to Close > Sequences to review, then activate when ready.")

    with open(os.path.join(os.path.dirname(__file__), "..", ".tmp", "realtor_pm_sequence.json"), "w") as f:
        json.dump({"sequence_id": seq["id"], "template_ids": [t1["id"], t2["id"], t3["id"]]}, f, indent=2)


if __name__ == "__main__":
    main()
