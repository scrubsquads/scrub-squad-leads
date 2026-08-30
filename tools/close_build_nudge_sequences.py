"""
Close CRM — Monthly Nudge Sequence Builder (Email only)

Creates ONE single-step, low-pressure "checking in" email sequence per
industry. These are DIFFERENT copy than the initial outreach sequences —
no discount pitch, just a light "still around if you need us" touch.

WHY A SEPARATE SEQUENCE PER INDUSTRY, SINGLE STEP:
Close will not let a contact re-subscribe to a sequence they already have
ANY subscription record on (active, finished, goal, error — doesn't
matter), so an "indefinite monthly repeat" cannot reuse the original
outreach sequence. tools/close_monthly_nudge.py handles the repeat by
DELETING the old nudge subscription record each month before creating a
fresh one, which only works cleanly against a single-step sequence
(no multi-step state to worry about resetting).

Usage:
    python close_build_nudge_sequences.py <industry>
    python close_build_nudge_sequences.py all

Industries: property_management, real_estate, construction, healthcare,
            warehouse, commercial, education

All sequences are created PAUSED — review copy, then activate in Close
before the monthly cron starts using them.
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

SENDER_ACCOUNT_ID = "emailacct_i5aPIJxDiZGPxJwhryabdcpSE5dCsWW7iymdxKhFyH8"
SENDER_NAME = "Sentel Mays"
SENDER_EMAIL = "sentelmays@scrubsquads.com"
SIGNATURE_PHONE = "786-838-4148"

# ---------------------------------------------------------------------------
# Nudge copy — distinct from initial outreach: shorter, no discount pitch,
# just a low-key "still here if you need us" check-in. Same for all
# industries with one line of industry-specific color.
# ---------------------------------------------------------------------------
NUDGE_INDUSTRY_LINE = {
    "property_management": "for the properties you manage",
    "real_estate": "for your listings or managed properties",
    "construction": "for job site or post-construction cleanup",
    "healthcare": "for your medical office",
    "warehouse": "for your facility",
    "commercial": "for your business",
    "education": "for your school or campus",
}

CAMPAIGN_LABELS = {
    "property_management": "PM Nudge",
    "real_estate": "Real Estate Nudge",
    "construction": "Construction Nudge",
    "healthcare": "Healthcare Nudge",
    "warehouse": "Warehouse Nudge",
    "commercial": "Commercial Nudge",
    "education": "Education Nudge",
}


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
        print(f"  ERROR {e.code}: {err[:500]}")
        raise


def build_nudge_sequence(key):
    if key not in NUDGE_INDUSTRY_LINE:
        raise ValueError(f"Unknown industry key: {key}")
    label = CAMPAIGN_LABELS[key]
    line = NUDGE_INDUSTRY_LINE[key]
    print(f"\n--- {label}: template + sequence ---")

    body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        f"Just a quick check-in — this is Sentel with Scrub Squad. We reached out "
        f"a while back about cleaning {line}, and I know timing isn't always "
        "right the first time around.<br><br>"
        "No pitch this time, just wanted to stay on your radar in case a "
        "cleaning need has come up since. Still happy to offer 25% off your "
        "first cleaning whenever you're ready to try us.<br><br>"
        f"Reply here or call/text me anytime at {SIGNATURE_PHONE}.<br><br>"
        "Thanks,<br>Sentel<br>Scrub Squad"
    )
    tmpl = api_post("email_template/", {
        "name": f"{label} | Monthly Check-In",
        "subject": "Still here if you need us",
        "body": body,
        "is_shared": True,
    })
    print(f"  Template: {tmpl['name']}")

    seq = api_post("sequence/", {
        "name": f"{label} - Monthly Re-Engagement",
        "sender_account_id": SENDER_ACCOUNT_ID,
        "sender_name": SENDER_NAME,
        "sender_email": SENDER_EMAIL,
        "status": "paused",
        "timezone": "America/New_York",
        "steps": [
            {"delay": 0, "step_type": "email", "email_template_id": tmpl["id"], "threading": "new_thread"},
        ],
    })
    print(f"  Created sequence: {seq['name']} ({seq['id']})")
    return {"sequence_id": seq["id"], "template_id": tmpl["id"]}


def main():
    if not API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        sys.exit(1)

    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <{'|'.join(NUDGE_INDUSTRY_LINE.keys())}|all>")
        sys.exit(1)

    keys = list(NUDGE_INDUSTRY_LINE.keys()) if sys.argv[1] == "all" else [sys.argv[1]]

    out_path = os.path.join(os.path.dirname(__file__), "..", ".tmp", "nudge_sequences.json")
    existing = {}
    if os.path.exists(out_path):
        with open(out_path) as f:
            existing = json.load(f)

    for key in keys:
        result = build_nudge_sequence(key)
        existing[key] = result

    with open(out_path, "w") as f:
        json.dump(existing, f, indent=2)

    print(f"\nDONE. Nudge sequences created PAUSED. Saved mapping to {out_path}")
    print("Review copy in Close > Workflows > Archived, then activate before enabling the monthly cron.")


if __name__ == "__main__":
    main()
