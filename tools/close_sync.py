"""
Close CRM — Sync New Leads from Google Sheets
Reads Leads + Contacts from Google Sheets, creates them in Close CRM,
and subscribes to the appropriate email sequence.

Deduplicates using place_id custom field in Close.
Run daily after enrichment (Job 3 in GitHub Actions pipeline).
"""
import json
import time
import urllib.request
import urllib.error
import urllib.parse
import base64
import os
import sys
import logging
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Load .env if running locally (GitHub Actions injects secrets as env vars)
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists() and not os.environ.get("GITHUB_ACTIONS"):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Close CRM config
# ---------------------------------------------------------------------------
CLOSE_API_KEY = os.environ.get("CLOSE_API_KEY", "")
BASE_URL = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(f"{CLOSE_API_KEY}:".encode()).decode()
SENDER = "emailacct_dFJqVFzngLhlf9T7g6lwJR8wo9F6wrgkEPZ0rfFJWDy"

# Lead status
NEW_LEAD_STATUS = "stat_d857QdxZmTJKNUcl1XZMPcLgIG8BcQCylkQqiHstS2q"

# Sequences
SEQ_COMMERCIAL = "seq_2Chrg4DReemWf9iAnu3i9R"
SEQ_EDUCATION = "seq_4RJzLUfIitjgtjJus682KO"

EDUCATION_INDUSTRIES = {"Education"}

# ---------------------------------------------------------------------------
# Close API helpers
# ---------------------------------------------------------------------------
def close_get(path):
    req = urllib.request.Request(
        f"{BASE_URL}/{path}",
        headers={"Authorization": AUTH}
    )
    resp = urllib.request.urlopen(req)
    time.sleep(0.3)
    return json.loads(resp.read().decode())


def close_post(path, data):
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
        logger.error("  ERROR %d: %s", e.code, err[:300])
        return None


# ---------------------------------------------------------------------------
# Google Sheets helpers (reuse existing patterns)
# ---------------------------------------------------------------------------
def get_sheets_client():
    import gspread
    sa_json = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    return gspread.service_account_from_dict(sa_json)


def read_all_leads(spreadsheet):
    """Read all leads from the Leads tab as list of dicts."""
    ws = spreadsheet.worksheet("Leads")
    return ws.get_all_records()


def read_all_contacts(spreadsheet):
    """Read all contacts from the Contacts tab as list of dicts."""
    ws = spreadsheet.worksheet("Contacts")
    return ws.get_all_records()


# ---------------------------------------------------------------------------
# Close CRM field discovery
# ---------------------------------------------------------------------------
def get_custom_field_map():
    """Get a map of custom field name → field API key (e.g., 'custom.cf_xxx')."""
    fields = close_get("custom_field/lead/")
    field_map = {}
    for f in fields["data"]:
        # Close uses 'custom.cf_xxx' format for setting values
        field_map[f["name"]] = f"custom.{f['id']}"
    return field_map


def get_existing_leads_dedup():
    """Get place_ids AND lead names from Close for dual deduplication.

    Returns (place_ids: set, lead_names: set).
    Uses both because older leads may not have Place ID set.
    """
    place_ids = set()
    lead_names = set()
    has_more = True
    offset = 0

    # Get the Place ID custom field ID
    fields = close_get("custom_field/lead/")
    place_id_field = None
    for f in fields["data"]:
        if f["name"] == "Place ID":
            place_id_field = f["id"]
            break

    field_param = f",custom.{place_id_field}" if place_id_field else ""

    while has_more:
        data = close_get(f"lead/?_limit=200&_skip={offset}&_fields=display_name{field_param}")
        for lead in data.get("data", []):
            # Collect place_id if set
            if place_id_field:
                pid = lead.get("custom", {}).get(place_id_field, "")
                if pid:
                    place_ids.add(str(pid).strip())
            # Collect lead name (normalized lowercase for matching)
            name = lead.get("display_name", "").strip().lower()
            if name:
                lead_names.add(name)
        has_more = data.get("has_more", False)
        offset += 200

    return place_ids, lead_names


# ---------------------------------------------------------------------------
# Lead creation
# ---------------------------------------------------------------------------
def split_name(full_name):
    """Split 'John Smith' into ('John', 'Smith')."""
    parts = str(full_name).strip().split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    elif len(parts) == 1:
        return parts[0], ""
    return "", ""


def build_address(full_address):
    """Parse a full address into Close address fields (best effort)."""
    # Close expects structured address, but we'll use the display field
    if not full_address:
        return {}
    return {
        "addresses": [{
            "label": "business",
            "address_1": str(full_address),
            "country": "US",
        }]
    }


def create_lead_in_close(lead, contacts, field_map):
    """Create a lead in Close with contacts. Returns (lead_data, first_contact_id)."""

    # Build custom fields
    custom = {}
    field_mappings = {
        "Region": lead.get("region", ""),
        "Place ID": lead.get("place_id", ""),
        "Google Maps Link": lead.get("google_maps_link", ""),
    }

    # Map business_type to Industry
    btype = lead.get("business_type", "")
    if btype:
        # Map scrape query types to Close industry values
        industry_map = {
            "Medical Offices": "Healthcare",
            "Property Management Companies": "Property Management",
            "Construction Companies": "Construction",
            "Schools": "Education",
            "Assisted Living": "Assisted Living",
            "Car Dealerships": "Car Dealerships",
            "Fitness Centers": "Fitness Centers",
            "Hotels": "Hospitality",
            "Warehouses": "Warehouse",
            "Office Buildings": "Commercial Building",
            "Retail Stores": "Retail",
        }
        industry = industry_map.get(btype, btype)
        field_mappings["Industry"] = industry

    # Also check contact-level industry from Apollo
    if contacts and not field_mappings.get("Industry"):
        apollo_industry = contacts[0].get("company_industry", "")
        if apollo_industry:
            field_mappings["Industry"] = apollo_industry

    for field_name, value in field_mappings.items():
        if value and field_name in {k.replace("custom.", ""): k for k in field_map}.values():
            pass  # will set below
        field_key = field_map.get(field_name)
        if field_key and value:
            # field_key is "custom.cf_xxx", we need just "cf_xxx" for the custom dict
            cf_id = field_key.replace("custom.", "")
            custom[cf_id] = str(value)

    # Build lead payload
    lead_data = {
        "name": lead.get("business_name", "Unknown"),
        "status_id": NEW_LEAD_STATUS,
        "custom": custom,
    }

    # Add URL
    website = lead.get("website", "")
    if website:
        if not website.startswith("http"):
            website = "https://" + website
        lead_data["url"] = website

    # Add addresses
    address = lead.get("full_address", "")
    if address:
        lead_data["addresses"] = [{"address_1": str(address), "country": "US"}]

    # Build contacts
    close_contacts = []
    for c in contacts:
        first, last = split_name(c.get("full_name", ""))
        contact = {
            "name": c.get("full_name", ""),
            "title": c.get("title", ""),
        }
        if first:
            contact["first_name"] = first
        if last:
            contact["last_name"] = last

        # Add email
        email = c.get("email", "")
        if email:
            contact["emails"] = [{"email": str(email), "type": "office"}]

        # Add phone
        phone = c.get("phone", "")
        if phone:
            contact["phones"] = [{"phone": str(phone), "type": "office"}]

        close_contacts.append(contact)

    # If no contacts from Apollo, add a bare contact with business phone/email
    if not close_contacts:
        bare = {"name": lead.get("business_name", "")}
        if lead.get("phone"):
            bare["phones"] = [{"phone": str(lead["phone"]), "type": "office"}]
        if lead.get("email"):
            bare["emails"] = [{"email": str(lead["email"]), "type": "office"}]
        close_contacts.append(bare)

    lead_data["contacts"] = close_contacts

    # Create in Close
    result = close_post("lead/", lead_data)
    if not result:
        return None, None

    # Get first contact ID (for sequence subscription)
    first_contact_id = None
    if result.get("contacts"):
        for contact in result["contacts"]:
            if contact.get("emails"):
                first_contact_id = contact["id"]
                break
        if not first_contact_id and result["contacts"]:
            first_contact_id = result["contacts"][0]["id"]

    return result, first_contact_id


def subscribe_to_sequence(contact_id, sequence_id):
    """Subscribe a contact to an email sequence."""
    if not contact_id:
        return False
    result = close_post("sequence_subscription/", {
        "sequence_id": sequence_id,
        "contact_id": contact_id,
        "sender_account_id": SENDER,
        "sender_name": "Christian",
        "sender_email": "christian@scrubsquads.com",
    })
    return result is not None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not CLOSE_API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        sys.exit(1)
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON not set")
        sys.exit(1)

    print("=" * 60)
    print("Close CRM Sync — Google Sheets -> Close")
    print("=" * 60)

    # 1. Get custom field map from Close
    print("\nLoading Close custom fields...")
    field_map = get_custom_field_map()
    print(f"  Found {len(field_map)} custom fields")

    # 2. Get existing leads from Close (for dedup by place_id + name)
    print("Loading existing leads from Close...")
    existing_pids, existing_names = get_existing_leads_dedup()
    print(f"  {len(existing_pids)} leads with Place ID, {len(existing_names)} total lead names")

    # 3. Read leads + contacts from Google Sheets
    print("Reading Google Sheets...")
    client = get_sheets_client()
    spreadsheet = client.open_by_key(os.environ["GOOGLE_SHEET_ID"])

    all_leads = read_all_leads(spreadsheet)
    all_contacts = read_all_contacts(spreadsheet)
    print(f"  Leads tab: {len(all_leads)} rows")
    print(f"  Contacts tab: {len(all_contacts)} rows")

    # Build contact lookup by place_id
    contacts_by_pid = {}
    for c in all_contacts:
        pid = str(c.get("place_id", "")).strip()
        if pid:
            contacts_by_pid.setdefault(pid, []).append(c)

    # 4. Find new leads not in Close (check both place_id AND name)
    new_leads = []
    skipped_pid = 0
    skipped_name = 0
    for lead in all_leads:
        pid = str(lead.get("place_id", "")).strip()
        name = str(lead.get("business_name", "")).strip().lower()
        if pid and pid in existing_pids:
            skipped_pid += 1
            continue
        if name and name in existing_names:
            skipped_name += 1
            continue
        if pid:
            new_leads.append(lead)

    print(f"\n  Skipped (Place ID match): {skipped_pid}")
    print(f"  Skipped (name match): {skipped_name}")
    print(f"  New leads to sync: {len(new_leads)}")

    if not new_leads:
        print("Nothing to sync. All leads already in Close.")
        return

    # 5. Create leads in Close
    print(f"\nSyncing {len(new_leads)} leads to Close...")
    created = 0
    subscribed = 0
    errors = 0

    for i, lead in enumerate(new_leads):
        pid = str(lead.get("place_id", "")).strip()
        contacts = contacts_by_pid.get(pid, [])
        name = lead.get("business_name", "?")

        result, contact_id = create_lead_in_close(lead, contacts, field_map)
        if result:
            created += 1

            # Determine sequence based on industry
            industry = result.get("custom", {}).get(
                field_map.get("Industry", "").replace("custom.", ""), ""
            )
            if industry in EDUCATION_INDUSTRIES:
                seq_id = SEQ_EDUCATION
            else:
                seq_id = SEQ_COMMERCIAL

            # Subscribe to sequence if contact has email
            if contact_id:
                if subscribe_to_sequence(contact_id, seq_id):
                    subscribed += 1

            if (i + 1) % 25 == 0:
                print(f"  Progress: {i + 1}/{len(new_leads)} ({created} created, {subscribed} subscribed)")
        else:
            errors += 1
            logger.error("  Failed to create: %s", name)

    # 6. Summary
    print(f"\n{'=' * 60}")
    print("SYNC COMPLETE")
    print(f"{'=' * 60}")
    print(f"  New leads created: {created}")
    print(f"  Subscribed to sequences: {subscribed}")
    print(f"  Errors: {errors}")
    print(f"  Already in Close (skipped): {len(existing_pids)}")


if __name__ == "__main__":
    main()
