"""
Close CRM — Generic Industry-Specific Outreach Sequence Builder (Email + SMS)

Reusable generator: pass an industry config and it creates a 3-step email
sequence + 2-step SMS sequence, same structure/offer/number as the other
industry campaigns (Property Management, Real Estate), just with pitch
copy tailored to that industry's actual pain point.

Usage:
    python close_build_industry_sequence.py construction
    python close_build_industry_sequence.py healthcare
    python close_build_industry_sequence.py warehouse

All sequences are created PAUSED — review in Close > Workflows > Archived
before activating.
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
PHONE_NUMBER_ID = "phon_xgd6017OcW4UHTlmpQeZmvRvCCUkkf3zQlYVgvKfISD"  # 786-838-4148
SIGNATURE_PHONE = "786-838-4148"

# ---------------------------------------------------------------------------
# Industry configs — each defines the hook (pain point), the pitch bullets,
# and short SMS copy. Same 25% first-clean offer and structure across all.
# ---------------------------------------------------------------------------
INDUSTRIES = {
    "construction": {
        "display_name": "Construction Companies",
        "campaign_label": "Construction",
        "hook": "post-construction and final-clean services",
        "pain_point": "getting a job site handed over clean, on inspection-ready standards, without holding up your closing",
        "bullets": [
            "Fast turnaround so a delayed final clean doesn't hold up your handover or closing",
            "Heavy-duty post-construction cleaning — dust, debris, and residue, not just a light wipe-down",
            "Direct communication — a real person to reach, not a call center",
        ],
        "subject1": "Post-construction cleanup for {{ lead.name }}'s job sites",
        "email_open": "we handle post-construction and final cleaning for job sites across Miami-Dade, Homestead, and the Keys.",
        "reliability_line": "a late final clean can delay your handover or closing date. That's the #1 thing we optimize for: showing up on time so your project timeline never slips because of us.",
        "sms_service": "post-construction & final cleaning",
    },
    "healthcare": {
        "display_name": "Medical Offices / Healthcare",
        "campaign_label": "Healthcare",
        "hook": "medical-grade cleaning for healthcare facilities",
        "pain_point": "keeping patient-facing spaces spotless and sanitized on a schedule that doesn't disrupt appointments",
        "bullets": [
            "Flexible scheduling around your patient hours — early morning, evening, or weekend cleanings available",
            "Consistent, checklist-based sanitizing so every visit meets the same standard",
            "Direct communication — a real person to reach, not a call center",
        ],
        "subject1": "Medical-grade cleaning for {{ lead.name }}",
        "email_open": "we handle cleaning for medical offices and healthcare facilities across Miami-Dade, Homestead, and the Keys.",
        "reliability_line": "a missed or late cleaning in a patient-facing space isn't just inconvenient, it's a real problem. That's the #1 thing we optimize for: showing up on time, every time.",
        "sms_service": "medical office cleaning",
    },
    "warehouse": {
        "display_name": "Warehouse / Industrial",
        "campaign_label": "Warehouse",
        "hook": "warehouse and industrial facility cleaning",
        "pain_point": "cleaning a large facility without disrupting operations or shipping schedules",
        "bullets": [
            "Scheduling around your shift and shipping schedule, not the other way around",
            "Equipped to handle large facility square footage, not just small offices",
            "Direct communication — a real person to reach, not a call center",
        ],
        "subject1": "Facility cleaning for {{ lead.name }}",
        "email_open": "we handle cleaning for warehouses and industrial facilities across Miami-Dade, Homestead, and the Keys.",
        "reliability_line": "a cleaning crew that disrupts your operations or shows up late is worse than useless. That's the #1 thing we optimize for: working around your schedule, reliably.",
        "sms_service": "warehouse/facility cleaning",
    },
    "commercial": {
        "display_name": "General Commercial",
        "campaign_label": "Commercial",
        "hook": "commercial cleaning for businesses of all types",
        "pain_point": "keeping your space consistently clean without having to manage it yourself",
        "bullets": [
            "Flexible scheduling that works around your hours, not the other way around",
            "Consistent, checklist-based cleaning so every visit meets the same standard",
            "Direct communication — a real person to reach, not a call center",
        ],
        "subject1": "Commercial cleaning for {{ lead.name }}",
        "email_open": "we handle commercial cleaning for businesses across Miami-Dade, Homestead, and the Keys.",
        "reliability_line": "a cleaning crew that's inconsistent or shows up late reflects on your business too. That's the #1 thing we optimize for: showing up on time, every time.",
        "sms_service": "commercial cleaning",
    },
}


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


def build_email_sequence(key, cfg):
    label = cfg["campaign_label"]
    print(f"\n--- {label}: Email templates ---")

    t1_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        f"I'm Sentel with Scrub Squad — {cfg['email_open']}<br><br>"
        "A few things that make us easy to work with:<br><br>"
        + "".join(f"- {b}<br>" for b in cfg["bullets"]) + "<br>"
        f"If {cfg['pain_point']} is something you deal with, I'd love to be "
        "your go-to. Happy to offer 25% off your first cleaning so you can "
        "see the quality for yourself, no obligation after that.<br><br>"
        f"Reply here or call/text me directly at {SIGNATURE_PHONE}.<br><br>"
        "Thanks,<br>Sentel<br>Scrub Squad"
    )
    t1 = api_post("email_template/", {
        "name": f"{label} | Step 1 - Initial Outreach",
        "subject": cfg["subject1"],
        "body": t1_body,
        "is_shared": True
    })
    print(f"  Template: {t1['name']}")

    t2_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        f"Just following up on my note about cleaning for {{{{ lead.name }}}}.<br><br>"
        f"I know {cfg['reliability_line']}<br><br>"
        "If a cleaning need ever comes up, I'd be glad to quote it — no "
        "obligation.<br><br>"
        f"Reply here or reach me at {SIGNATURE_PHONE}.<br><br>"
        "Best,<br>Sentel<br>Scrub Squad"
    )
    t2 = api_post("email_template/", {
        "name": f"{label} | Step 2 - Reliability Follow-Up",
        "subject": "Re: " + cfg["subject1"],
        "body": t2_body,
        "is_shared": True
    })
    print(f"  Template: {t2['name']}")

    t3_body = (
        'Hi {{ contact.first_name | default:"there" }},<br><br>'
        "Last note from me — don't want to clutter your inbox. If a "
        "cleaning need ever comes up for {{ lead.name }}, keep Scrub Squad "
        "in mind. First cleaning is 25% off, no risk in trying us.<br><br>"
        f"You can always reach me at {SIGNATURE_PHONE} — no pressure either "
        "way.<br><br>"
        "Best,<br>Sentel<br>Scrub Squad"
    )
    t3 = api_post("email_template/", {
        "name": f"{label} | Step 3 - Low-Pressure Close",
        "subject": "Keeping Scrub Squad in your back pocket",
        "body": t3_body,
        "is_shared": True
    })
    print(f"  Template: {t3['name']}")

    seq = api_post("sequence/", {
        "name": f"{label} Outreach",
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
    print(f"  Created sequence: {seq['name']} ({seq['id']})")
    return {"sequence_id": seq["id"], "template_ids": [t1["id"], t2["id"], t3["id"]]}


def build_sms_sequence(key, cfg):
    label = cfg["campaign_label"]
    print(f"\n--- {label}: SMS templates ---")

    sms1 = (
        'Hi {{ contact.first_name | default:"there" }}, this is Sentel with '
        f"Scrub Squad. We do {cfg['sms_service']} across Miami-Dade, "
        "Homestead & the Keys - fast, reliable. 25% off your first cleaning "
        f"if you'd like to try us. Interested? Reply here or call/text "
        f"{SIGNATURE_PHONE}."
    )
    t1 = api_post("sms_template/", {"name": f"{label} SMS | Step 1 - Initial Outreach", "text": sms1, "is_shared": True})
    print(f"  Template: {t1['name']} ({len(sms1)} chars)")

    sms2 = (
        'Hi {{ contact.first_name | default:"there" }}, following up - if a '
        f"cleaning need ever comes up, keep Scrub Squad in mind. Reliable, "
        f"on-time. 25% off your first one. Text {SIGNATURE_PHONE} anytime."
    )
    t2 = api_post("sms_template/", {"name": f"{label} SMS | Step 2 - Follow-Up", "text": sms2, "is_shared": True})
    print(f"  Template: {t2['name']} ({len(sms2)} chars)")

    seq = api_post("sequence/", {
        "name": f"{label} SMS Outreach",
        "sender_phone_number_id": PHONE_NUMBER_ID,
        "status": "paused",
        "timezone": "America/New_York",
        "steps": [
            {"delay": 0, "step_type": "sms", "sms_template_id": t1["id"]},
            {"delay": DAY * 5, "step_type": "sms", "sms_template_id": t2["id"]},
        ]
    })
    print(f"  Created sequence: {seq['name']} ({seq['id']})")
    return {"sequence_id": seq["id"], "template_ids": [t1["id"], t2["id"]]}


def main():
    if not API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        sys.exit(1)

    if len(sys.argv) < 2 or sys.argv[1] not in INDUSTRIES:
        print(f"Usage: python {sys.argv[0]} <{'|'.join(INDUSTRIES.keys())}>")
        sys.exit(1)

    key = sys.argv[1]
    cfg = INDUSTRIES[key]
    print(f"Building campaigns for: {cfg['campaign_label']}")

    email_result = build_email_sequence(key, cfg)
    sms_result = build_sms_sequence(key, cfg)

    out_path = os.path.join(os.path.dirname(__file__), "..", ".tmp", f"industry_{key}_sequences.json")
    with open(out_path, "w") as f:
        json.dump({"email": email_result, "sms": sms_result}, f, indent=2)

    print(f"\nDONE. Both sequences created PAUSED for {cfg['campaign_label']}.")
    print("Review in Close > Workflows > Archived before activating.")


if __name__ == "__main__":
    main()
