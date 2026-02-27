"""
Close CRM — Bulk Subscribe Leads to Email Sequences
Subscribes leads based on their current status:
  - New Lead → Initial Outreach (Commercial or Education based on Industry)
  - Attempting Contact → Re-Engagement - Stale Leads
  - Under Contract → Under Contract Nurture
  - In-House → In-House Conversion
"""
import json
import time
import urllib.request
import urllib.error
import urllib.parse
import base64
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

API_KEY = os.environ.get("CLOSE_API_KEY", "")
BASE_URL = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(f"{API_KEY}:".encode()).decode()

# Sequence IDs
SEQUENCES = {
    "commercial": "seq_2Chrg4DReemWf9iAnu3i9R",
    "education": "seq_4RJzLUfIitjgtjJus682KO",
    "re_engagement": "seq_7E8OUM4hJv0TMYqs0DTpnR",
    "under_contract": "seq_7VtIyORkElb8PwsN8xlvvW",
    "in_house": "seq_5niHTBZZR5z3P8Ef8p5lRH",
}

EDUCATION_INDUSTRIES = {"Education"}

BATCH_SIZE = 50
BATCH_DELAY = 2  # seconds between batches


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


def get_leads_with_emails(status_label):
    """Fetch all leads in a status that have email contacts."""
    leads = []
    has_more = True
    offset = 0
    q = urllib.parse.quote(f'lead_status:"{status_label}"')

    while has_more:
        data = api_get(
            f"lead/?_limit=100&_skip={offset}"
            f"&query={q}"
            f"&_fields=id,display_name,contacts,custom"
        )
        for lead in data.get("data", []):
            # Find first contact with an email
            contact_id = None
            for c in lead.get("contacts", []):
                if c.get("emails"):
                    contact_id = c["id"]
                    break
            if contact_id:
                industry = lead.get("custom", {}).get("Industry", "")
                leads.append({
                    "lead_id": lead["id"],
                    "contact_id": contact_id,
                    "name": lead.get("display_name", "?"),
                    "industry": industry,
                })
        offset += 100
        has_more = data.get("has_more", False)

    return leads


def subscribe_leads(leads, sequence_id, sequence_name):
    """Subscribe a list of leads to a sequence in batches."""
    total = len(leads)
    success = 0
    errors = 0

    for i in range(0, total, BATCH_SIZE):
        batch = leads[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"    Batch {batch_num}/{total_batches} ({len(batch)} leads)...")

        for lead in batch:
            result = api_post("sequence_subscription/", {
                "sequence_id": sequence_id,
                "contact_id": lead["contact_id"],
                "sender_account_id": "emailacct_dFJqVFzngLhlf9T7g6lwJR8wo9F6wrgkEPZ0rfFJWDy",
                "sender_name": "Christian",
                "sender_email": "christian@scrubsquads.com",
            })
            if result:
                success += 1
            else:
                errors += 1
                print(f"      Failed: {lead['name']}")

        if i + BATCH_SIZE < total:
            time.sleep(BATCH_DELAY)

    print(f"    Result: {success} subscribed, {errors} failed")
    return success, errors


def main():
    if not API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        sys.exit(1)

    total_subscribed = 0
    total_errors = 0

    # =================================================================
    # 1. New Leads → Commercial or Education sequence
    # =================================================================
    print("=" * 60)
    print("1. NEW LEADS → Initial Outreach")
    print("=" * 60)
    new_leads = get_leads_with_emails("New Lead")
    print(f"  Found {len(new_leads)} New Leads with email contacts")

    commercial_leads = [l for l in new_leads if l["industry"] not in EDUCATION_INDUSTRIES]
    education_leads = [l for l in new_leads if l["industry"] in EDUCATION_INDUSTRIES]

    print(f"  Commercial: {len(commercial_leads)}, Education: {len(education_leads)}")

    if commercial_leads:
        print(f"\n  Subscribing {len(commercial_leads)} to Initial Outreach - Commercial...")
        s, e = subscribe_leads(commercial_leads, SEQUENCES["commercial"], "Initial Outreach - Commercial")
        total_subscribed += s
        total_errors += e

    if education_leads:
        print(f"\n  Subscribing {len(education_leads)} to Initial Outreach - Education...")
        s, e = subscribe_leads(education_leads, SEQUENCES["education"], "Initial Outreach - Education")
        total_subscribed += s
        total_errors += e

    # =================================================================
    # 2. Attempting Contact → Re-Engagement
    # =================================================================
    print("\n" + "=" * 60)
    print("2. ATTEMPTING CONTACT → Re-Engagement")
    print("=" * 60)
    ac_leads = get_leads_with_emails("Attempting Contact")
    print(f"  Found {len(ac_leads)} Attempting Contact leads with email contacts")

    if ac_leads:
        print(f"\n  Subscribing {len(ac_leads)} to Re-Engagement - Stale Leads...")
        s, e = subscribe_leads(ac_leads, SEQUENCES["re_engagement"], "Re-Engagement")
        total_subscribed += s
        total_errors += e

    # =================================================================
    # 3. Under Contract → Under Contract Nurture
    # =================================================================
    print("\n" + "=" * 60)
    print("3. UNDER CONTRACT → Under Contract Nurture")
    print("=" * 60)
    uc_leads = get_leads_with_emails("Under Contract")
    print(f"  Found {len(uc_leads)} Under Contract leads with email contacts")

    if uc_leads:
        print(f"\n  Subscribing {len(uc_leads)} to Under Contract Nurture...")
        s, e = subscribe_leads(uc_leads, SEQUENCES["under_contract"], "Under Contract Nurture")
        total_subscribed += s
        total_errors += e

    # =================================================================
    # 4. In-House → In-House Conversion
    # =================================================================
    print("\n" + "=" * 60)
    print("4. IN-HOUSE → In-House Conversion")
    print("=" * 60)
    ih_leads = get_leads_with_emails("In-House")
    print(f"  Found {len(ih_leads)} In-House leads with email contacts")

    if ih_leads:
        print(f"\n  Subscribing {len(ih_leads)} to In-House Conversion...")
        s, e = subscribe_leads(ih_leads, SEQUENCES["in_house"], "In-House Conversion")
        total_subscribed += s
        total_errors += e

    # =================================================================
    # Summary
    # =================================================================
    print("\n" + "=" * 60)
    print("SUBSCRIPTION COMPLETE")
    print("=" * 60)
    print(f"  Total subscribed: {total_subscribed}")
    print(f"  Total errors: {total_errors}")
    print(f"\n  Breakdown:")
    print(f"    New Lead (Commercial): {len(commercial_leads)}")
    print(f"    New Lead (Education): {len(education_leads)}")
    print(f"    Attempting Contact: {len(ac_leads)}")
    print(f"    Under Contract: {len(uc_leads)}")
    print(f"    In-House: {len(ih_leads)}")


if __name__ == "__main__":
    main()
