"""
Close CRM — Build Email Sequences for Scrub Squad
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


def api_delete(path):
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", method="DELETE",
        headers={"Authorization": AUTH}
    )
    urllib.request.urlopen(req)
    time.sleep(0.3)


# Template IDs (existing)
T = {
    "commercial_1": "tmpl_xNwon8zcmW0R7WXZ2eVbfBHnRG4MsI6vfwbIeE9ICzH",
    "commercial_2": "tmpl_UAPYU33oucmZiJOMtqA9oTOXvKHnISy8GPeF7KzeZog",
    "commercial_3": "tmpl_Ct6FrMxPykqKRDvz8BXScv06VxBfcOaBKmaiPyo4nac",
    "commercial_4": "tmpl_hI5g7Ib4gQrZabd3N526JocpWhOvwYLwNzK50Oi1DLE",
    "commercial_6": "tmpl_KkZxpp7JLLO3BZTDqA041BZ6ZnRLKNmY3j5eslJRhCB",
    "commercial_check": "tmpl_Y9SIB9NhsKxzjYCE0gNinmW1REnOz6YkmJeIO6lY1CM",
    "education_1": "tmpl_alUW1vACRTZXlHUTkHo4Wlkm5MyjNac58XXLv8sqHc8",
    "education_2": "tmpl_uNgpRMOCUCGOc8dRZJNIl6pGX9MRHnDjA43FtUByfv4",
    "pricing": "tmpl_vT4HPppOE4E8JmsZUdgqYYu8S3sYmjeSTsAd1wk3TwI",
    "emails_opened": "tmpl_c8KXaWQqWqArVVJK3Vwy9ZDU22sm16aNoOJbOiJzQrH",
}


def main():
    if not API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        sys.exit(1)

    # =========================================
    # Delete old empty sequences
    # =========================================
    print("Deleting old sequences...")
    try:
        api_delete("sequence/seq_6toOOA3dmj8SaZqiRyylIR/")
        print("  Deleted: 2nd Email Campaign")
    except Exception:
        print("  Already deleted or not found")
    try:
        api_delete("sequence/seq_11sr39McnXxwBE0Gk2z2Fr/")
        print("  Deleted: Email Campaign")
    except Exception:
        print("  Already deleted or not found")

    # =========================================
    # 1. Initial Outreach (Commercial)
    # =========================================
    print("\nCreating: Initial Outreach - Commercial...")
    seq1 = api_post("sequence/", {
        "name": "Initial Outreach - Commercial",
        "sender_account_id": SENDER,
        "sender_name": "Christian",
        "sender_email": "christian@scrubsquads.com",
        "status": "paused",
        "timezone": "America/New_York",
        "steps": [
            {"delay": 0, "step_type": "email", "email_template_id": T["commercial_1"], "threading": "new_thread"},
            {"delay": DAY * 3, "step_type": "email", "email_template_id": T["commercial_2"], "threading": "old_thread"},
            {"delay": DAY * 4, "step_type": "email", "email_template_id": T["commercial_3"], "threading": "old_thread"},
            {"delay": DAY * 7, "step_type": "email", "email_template_id": T["commercial_4"], "threading": "old_thread"},
            {"delay": DAY * 7, "step_type": "email", "email_template_id": T["commercial_6"], "threading": "old_thread"},
        ]
    })
    print(f"  Created: {seq1['name']} ({seq1['id']}) - 5 steps over 21 days")

    # =========================================
    # 2. Education Outreach
    # =========================================
    print("\nCreating: Initial Outreach - Education...")
    seq2 = api_post("sequence/", {
        "name": "Initial Outreach - Education",
        "sender_account_id": SENDER,
        "sender_name": "Christian",
        "sender_email": "christian@scrubsquads.com",
        "status": "paused",
        "timezone": "America/New_York",
        "steps": [
            {"delay": 0, "step_type": "email", "email_template_id": T["education_1"], "threading": "new_thread"},
            {"delay": DAY * 5, "step_type": "email", "email_template_id": T["education_2"], "threading": "old_thread"},
            {"delay": DAY * 9, "step_type": "email", "email_template_id": T["pricing"], "threading": "old_thread"},
        ]
    })
    print(f"  Created: {seq2['name']} ({seq2['id']}) - 3 steps over 14 days")

    # =========================================
    # 3. Re-Engagement (Stale Leads)
    # =========================================
    print("\nCreating: Re-Engagement - Stale Leads...")
    seq3 = api_post("sequence/", {
        "name": "Re-Engagement - Stale Leads",
        "sender_account_id": SENDER,
        "sender_name": "Christian",
        "sender_email": "christian@scrubsquads.com",
        "status": "paused",
        "timezone": "America/New_York",
        "steps": [
            {"delay": 0, "step_type": "email", "email_template_id": T["emails_opened"], "threading": "new_thread"},
            {"delay": DAY * 5, "step_type": "email", "email_template_id": T["commercial_check"], "threading": "old_thread"},
            {"delay": DAY * 9, "step_type": "email", "email_template_id": T["commercial_4"], "threading": "old_thread"},
        ]
    })
    print(f"  Created: {seq3['name']} ({seq3['id']}) - 3 steps over 14 days")

    # =========================================
    # 4. Post-Walkthrough Follow Up
    # =========================================
    print("\nCreating post-walkthrough templates...")

    t1_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        "Great meeting you today! As promised, I'm putting together your custom "
        "cleaning proposal based on what we saw during the walkthrough.<br><br>"
        "You should have the full quote in your inbox within 24 hours. It will include:"
        "<br><br>"
        "- Scope of work tailored to your space<br>"
        "- Recommended cleaning frequency<br>"
        "- Transparent pricing with no hidden fees<br><br>"
        "In the meantime, if you have any questions or want to adjust anything we "
        "discussed, just reply to this email.<br><br>"
        "Looking forward to working with you!<br><br>"
        "Christian<br>Scrub Squads<br>786-838-4148"
    )
    t1 = api_post("email_template/", {
        "name": "Post-Walkthrough | Step 1 - Custom Quote",
        "subject": "{{ lead.name }} | Your Custom Cleaning Quote from Scrub Squads",
        "body": t1_body,
        "is_shared": True
    })
    print(f"  Template: {t1['name']}")

    t2_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        "Just checking in to see if you had a chance to review the cleaning proposal "
        "I sent over.<br><br>"
        "If anything needs adjusting - different frequency, specific areas of focus, "
        "or budget considerations - I'm happy to revise it. We want to make sure it "
        "fits your needs exactly.<br><br>"
        "Feel free to reply here or give me a call at 786-838-4148.<br><br>"
        "Christian<br>Scrub Squads"
    )
    t2 = api_post("email_template/", {
        "name": "Post-Walkthrough | Step 2 - Questions",
        "subject": "{{ lead.name }} | Any questions about the proposal?",
        "body": t2_body,
        "is_shared": True
    })
    print(f"  Template: {t2['name']}")

    t3_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        "Just a final follow-up on the cleaning proposal for {{ lead.name }}. "
        "I know these decisions take time, and there's no pressure.<br><br>"
        "If you'd like to move forward, we can usually start within a week of signing. "
        "If now isn't the right time, no worries at all - we'll be here when you're "
        "ready.<br><br>"
        "Either way, it was great seeing your space and I appreciate your time.<br><br>"
        "Best,<br>Christian<br>Scrub Squads<br>786-838-4148"
    )
    t3 = api_post("email_template/", {
        "name": "Post-Walkthrough | Step 3 - Ready When You Are",
        "subject": "{{ lead.name }} | Ready when you are",
        "body": t3_body,
        "is_shared": True
    })
    print(f"  Template: {t3['name']}")

    print("\nCreating: Post-Walkthrough Follow Up...")
    seq4 = api_post("sequence/", {
        "name": "Post-Walkthrough Follow Up",
        "sender_account_id": SENDER,
        "sender_name": "Christian",
        "sender_email": "christian@scrubsquads.com",
        "status": "paused",
        "timezone": "America/New_York",
        "steps": [
            {"delay": DAY * 1, "step_type": "email", "email_template_id": t1["id"], "threading": "new_thread"},
            {"delay": DAY * 3, "step_type": "email", "email_template_id": t2["id"], "threading": "old_thread"},
            {"delay": DAY * 3, "step_type": "email", "email_template_id": t3["id"], "threading": "old_thread"},
        ]
    })
    print(f"  Created: {seq4['name']} ({seq4['id']}) - 3 steps over 7 days")

    # =========================================
    # Summary
    # =========================================
    print("\n" + "=" * 50)
    print("ALL SEQUENCES CREATED (paused - ready to activate)")
    print("=" * 50)
    print(f"  1. {seq1['name']} - 5 emails over 21 days")
    print(f"  2. {seq2['name']} - 3 emails over 14 days")
    print(f"  3. {seq3['name']} - 3 emails over 14 days")
    print(f"  4. {seq4['name']} - 3 emails over 7 days")
    print()
    print("All sequences are PAUSED. Review them in Close, then activate when ready.")
    print("Go to: Close > Sequences (in left nav or via search)")


if __name__ == "__main__":
    main()
