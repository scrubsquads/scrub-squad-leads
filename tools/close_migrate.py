"""
Close CRM Migration Script — Scrub Squad Reorganization
========================================================
One-time script to restructure Close CRM:
  Phase 1: Create new lead statuses
  Phase 2: Create new custom fields
  Phase 3: Migrate leads from old → new statuses
  Phase 4: Delete old coaching custom fields
  Phase 5: Delete empty old lead statuses
  Phase 6: Update Sales Funnel pipeline
  Phase 7: Delete old Smart Views, create new ones
"""

import json
import time
import urllib.request
import urllib.parse
import urllib.error
import base64
import os
import sys

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("CLOSE_API_KEY", "")
BASE_URL = "https://api.close.com/api/v1"
AUTH_HEADER = "Basic " + base64.b64encode(f"{API_KEY}:".encode()).decode()
DELAY = 0.3  # seconds between API calls to avoid rate limits

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def api_request(method, path, data=None):
    """Make an authenticated request to the Close API."""
    url = f"{BASE_URL}/{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", AUTH_HEADER)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        resp = urllib.request.urlopen(req)
        if resp.status == 204:
            return {}
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"  ERROR {e.code}: {error_body[:300]}")
        raise


def api_get(path):
    time.sleep(DELAY)
    return api_request("GET", path)


def api_post(path, data):
    time.sleep(DELAY)
    return api_request("POST", path, data)


def api_put(path, data):
    time.sleep(DELAY)
    return api_request("PUT", path, data)


def api_delete(path):
    time.sleep(DELAY)
    return api_request("DELETE", path)


def get_all_leads_by_status(status_name):
    """Fetch all lead IDs with a given status (handles pagination)."""
    leads = []
    query = urllib.parse.quote(f'lead_status:"{status_name}"')
    has_more = True
    skip = 0
    limit = 100
    while has_more:
        path = f"lead/?_limit={limit}&_skip={skip}&_fields=id&query={query}"
        resp = api_get(path)
        batch = resp.get("data", [])
        leads.extend([l["id"] for l in batch])
        has_more = resp.get("has_more", False)
        skip += limit
    return leads


# ===========================================================================
# PHASE 1: Create new lead statuses
# ===========================================================================

def phase1_create_statuses():
    print("\n" + "=" * 60)
    print("PHASE 1: Create new lead statuses")
    print("=" * 60)

    # Get existing statuses
    resp = api_get("status/lead/")
    existing = {s["label"]: s["id"] for s in resp["data"]}
    print(f"  Existing statuses: {list(existing.keys())}")

    new_statuses = [
        "New Lead",
        "Attempting Contact",
        "Customer",
    ]

    created = {}
    for label in new_statuses:
        if label in existing:
            print(f"  SKIP: '{label}' already exists")
            created[label] = existing[label]
        else:
            result = api_post("status/lead/", {"label": label})
            created[label] = result["id"]
            print(f"  CREATED: '{label}' → {result['id']}")

    # Return full map of all statuses (old + new)
    resp = api_get("status/lead/")
    all_statuses = {s["label"]: s["id"] for s in resp["data"]}
    print(f"\n  All statuses now: {list(all_statuses.keys())}")
    return all_statuses


# ===========================================================================
# PHASE 2: Create new custom fields
# ===========================================================================

def phase2_create_custom_fields():
    print("\n" + "=" * 60)
    print("PHASE 2: Create new custom fields")
    print("=" * 60)

    resp = api_get("custom_field/lead/")
    existing = {f["name"]: f["id"] for f in resp["data"]}
    print(f"  Existing fields: {list(existing.keys())}")

    new_fields = [
        {"name": "Region", "type": "choices",
         "choices": ["Miami-Dade", "Broward", "Homestead", "Key Largo"]},
        {"name": "Estimated Sq Ft", "type": "number"},
        {"name": "Service Frequency", "type": "choices",
         "choices": ["Daily", "3x/Week", "2x/Week", "Weekly", "Bi-Weekly", "One-Time"]},
        {"name": "Current Cleaning Provider", "type": "text"},
        {"name": "Contract End Date", "type": "date"},
        {"name": "Google Maps Link", "type": "text"},
        {"name": "Place ID", "type": "text"},
    ]

    for field in new_fields:
        if field["name"] in existing:
            print(f"  SKIP: '{field['name']}' already exists")
        else:
            result = api_post("custom_field/lead/", field)
            print(f"  CREATED: '{field['name']}' ({field['type']}) → {result['id']}")

    # Update Industry choices to add Government and Hospitality
    if "Industry" in existing:
        industry_id = existing["Industry"]
        # Get current field details
        field_data = api_get(f"custom_field/lead/{industry_id}/")
        current_choices = field_data.get("choices", [])
        additions = ["Government", "Hospitality"]
        new_choices = current_choices[:]
        for a in additions:
            if a not in new_choices:
                new_choices.append(a)
        if new_choices != current_choices:
            api_put(f"custom_field/lead/{industry_id}/", {"choices": sorted(new_choices)})
            print(f"  UPDATED: 'Industry' — added {additions}")
        else:
            print(f"  SKIP: 'Industry' already has Government/Hospitality")

    # Update Lead Source choices
    if "Lead Source" in existing:
        source_id = existing["Lead Source"]
        field_data = api_get(f"custom_field/lead/{source_id}/")
        current_choices = field_data.get("choices", [])
        additions = ["Outscraper", "Apollo", "Cold Call", "Door Knock"]
        new_choices = current_choices[:]
        for a in additions:
            if a not in new_choices:
                new_choices.append(a)
        if new_choices != current_choices:
            api_put(f"custom_field/lead/{source_id}/", {"choices": sorted(new_choices)})
            print(f"  UPDATED: 'Lead Source' — added {additions}")
        else:
            print(f"  SKIP: 'Lead Source' already has new choices")

    print("  Done.")


# ===========================================================================
# PHASE 3: Migrate leads
# ===========================================================================

def phase3_migrate_leads(all_statuses):
    print("\n" + "=" * 60)
    print("PHASE 3: Migrate leads to new statuses")
    print("=" * 60)

    # Mapping: old_status_label → new_status_label
    migration_map = {
        "Cold Lead": "New Lead",
        "No Answer | VM": "Attempting Contact",
        "Email Campaign 1": "Attempting Contact",
        "Email Campaign 2": "Attempting Contact",
        "Email Campaign 3": "Attempting Contact",
        # "Contacted" stays "Contacted" — no migration needed
        # "Follow Up" stays "Follow Up" — no migration needed
        # "Hot Lead" stays "Hot Lead" — no migration needed
        # "Under Contract" stays "Under Contract" — no migration needed
        # "In-House" stays "In-House" — no migration needed
        # "Walkthrough Scheduled" stays "Walkthrough Scheduled" — no migration needed
        "Opportunity Won": "Customer",
        "Opportunity Lost": "Not Interested",
        # "Not Interested" stays "Not Interested" — no migration needed
        # "Do Not Contact" stays "Do Not Contact" — no migration needed
        "Residential": "Do Not Contact",
        "Providers": "Do Not Contact",
        "Final Interview": "Do Not Contact",
    }

    total_migrated = 0
    for old_label, new_label in migration_map.items():
        if old_label not in all_statuses:
            print(f"  SKIP: '{old_label}' status not found (already deleted?)")
            continue
        if new_label not in all_statuses:
            print(f"  ERROR: Target status '{new_label}' not found!")
            continue

        new_status_id = all_statuses[new_label]
        print(f"\n  Migrating '{old_label}' → '{new_label}'...")
        lead_ids = get_all_leads_by_status(old_label)
        print(f"    Found {len(lead_ids)} leads")

        for i, lead_id in enumerate(lead_ids):
            api_put(f"lead/{lead_id}/", {"status_id": new_status_id})
            total_migrated += 1
            if (i + 1) % 25 == 0:
                print(f"    ... migrated {i + 1}/{len(lead_ids)}")

        if lead_ids:
            print(f"    Migrated {len(lead_ids)} leads")

    print(f"\n  TOTAL MIGRATED: {total_migrated} leads")
    return total_migrated


# ===========================================================================
# PHASE 4: Delete old coaching custom fields
# ===========================================================================

def phase4_delete_custom_fields():
    print("\n" + "=" * 60)
    print("PHASE 4: Delete old coaching custom fields")
    print("=" * 60)

    resp = api_get("custom_field/lead/")
    existing = {f["name"]: f["id"] for f in resp["data"]}

    fields_to_delete = [
        "Budget/Startup Capital",
        "Commitment/hours they're willing to invest",
        "Course/Product Interested In Next",
        "Course/Product Purchased",
        "Custom Field",
        "Experience with coaches/consultants?",
        "Goals in Life/Business",
        "How would they describe themselves?",
        "Objections",
        "What made them sign up?",
        "Background Info",
    ]

    for name in fields_to_delete:
        if name in existing:
            try:
                api_delete(f"custom_field/lead/{existing[name]}/")
                print(f"  DELETED: '{name}'")
            except Exception as e:
                print(f"  FAILED to delete '{name}': {e}")
        else:
            print(f"  SKIP: '{name}' not found (already deleted?)")

    print("  Done.")


# ===========================================================================
# PHASE 5: Delete old lead statuses
# ===========================================================================

def phase5_delete_old_statuses(all_statuses):
    print("\n" + "=" * 60)
    print("PHASE 5: Delete old lead statuses")
    print("=" * 60)

    statuses_to_delete = [
        "Cold Lead",
        "No Answer | VM",
        "Email Campaign 1",
        "Email Campaign 2",
        "Email Campaign 3",
        "Opportunity Won",
        "Opportunity Lost",
        "Residential",
        "Providers",
        "Final Interview",
    ]

    for label in statuses_to_delete:
        if label not in all_statuses:
            print(f"  SKIP: '{label}' not found (already deleted?)")
            continue

        status_id = all_statuses[label]
        # Verify it's empty first
        leads = get_all_leads_by_status(label)
        if leads:
            print(f"  WARNING: '{label}' still has {len(leads)} leads — skipping delete")
            continue

        try:
            api_delete(f"status/lead/{status_id}/")
            print(f"  DELETED: '{label}'")
        except Exception as e:
            print(f"  FAILED to delete '{label}': {e}")

    print("  Done.")


# ===========================================================================
# PHASE 6: Update Sales Funnel pipeline
# ===========================================================================

def phase6_update_pipeline():
    print("\n" + "=" * 60)
    print("PHASE 6: Update Sales Funnel pipeline")
    print("=" * 60)

    # Get current opportunity statuses
    resp = api_get("status/opportunity/")
    opp_statuses = {s["label"]: s["id"] for s in resp["data"]}
    print(f"  Current opp statuses: {list(opp_statuses.keys())}")

    # Create "Negotiating" status if it doesn't exist
    if "Negotiating" not in opp_statuses:
        result = api_post("status/opportunity/", {
            "label": "Negotiating",
            "type": "active",
            "pipeline_id": "pipe_15eEMDPiaVIKGlB9JPWvt7"
        })
        print(f"  CREATED: 'Negotiating' → {result['id']}")
        opp_statuses["Negotiating"] = result["id"]
    else:
        print(f"  SKIP: 'Negotiating' already exists")

    # Reorder pipeline: Walkthrough Scheduled → Walkthrough Completed → Proposal Sent → Negotiating → Won / Lost
    # Remove: Meeting Booked, Meeting Held, No Show, On Hold
    desired_order = [
        opp_statuses["Walkthrough Scheduled"],
        opp_statuses["Walkthrough Completed"],
        opp_statuses["Proposal Sent"],
        opp_statuses["Negotiating"],
        opp_statuses["Won"],
        opp_statuses["Lost"],
    ]

    try:
        api_put("pipeline/pipe_15eEMDPiaVIKGlB9JPWvt7/", {
            "statuses": desired_order
        })
        print("  UPDATED: Sales Funnel pipeline reordered")
    except Exception as e:
        print(f"  NOTE: Pipeline reorder may need manual adjustment: {e}")
        print("  The new 'Negotiating' status was created — you can drag/drop in Close UI")

    print("  Done.")


# ===========================================================================
# PHASE 7: Smart Views
# ===========================================================================

def phase7_smart_views():
    print("\n" + "=" * 60)
    print("PHASE 7: Rebuild Smart Views")
    print("=" * 60)

    # Get all saved searches
    resp = api_get("saved_search/?_type=lead")
    views = {sv["name"]: sv["id"] for sv in resp.get("data", [])}
    print(f"  Current views: {list(views.keys())}")

    # Delete old views (keep Veteran Interior Construction)
    views_to_delete = [
        "Google Leads 2", "Google Leads",
        "Jan'26", "October 2", "October1",
        "September2", "September1", "August", "July",
        "Hot Leads", "Follow Up", "Warehouse",
        "Car Dealerships", "Education", "Property Management",
        "Residential Leads", "Providers", "Construction",
    ]

    for name in views_to_delete:
        if name in views:
            try:
                api_delete(f"saved_search/{views[name]}/")
                print(f"  DELETED view: '{name}'")
            except Exception as e:
                print(f"  FAILED to delete '{name}': {e}")
        else:
            print(f"  SKIP: view '{name}' not found")

    # Create new Smart Views using Close search query syntax
    new_views = [
        {
            "name": "New Leads — First Touch",
            "query": 'lead_status:"New Lead" sort:created',
            "is_shared": True,
        },
        {
            "name": "Attempting Contact — Call Queue",
            "query": 'lead_status:"Attempting Contact" sort:updated',
            "is_shared": True,
        },
        {
            "name": "Hot Leads",
            "query": 'lead_status:"Hot Lead" sort:updated',
            "is_shared": True,
        },
        {
            "name": "Follow Ups",
            "query": 'lead_status:"Follow Up" sort:updated',
            "is_shared": True,
        },
        {
            "name": "Under Contract",
            "query": 'lead_status:"Under Contract" sort:updated',
            "is_shared": True,
        },
        {
            "name": "In-House — Pitch Outsourcing",
            "query": 'lead_status:"In-House" sort:updated',
            "is_shared": True,
        },
        {
            "name": "Walkthroughs Scheduled",
            "query": 'lead_status:"Walkthrough Scheduled" sort:updated',
            "is_shared": True,
        },
        {
            "name": "Customers",
            "query": 'lead_status:"Customer" sort:updated',
            "is_shared": True,
        },
        {
            "name": "Stale Leads (14+ Days)",
            "query": 'lead_status:"Attempting Contact" last_activity > 14 days ago sort:updated',
            "is_shared": True,
        },
        {
            "name": "Not Interested",
            "query": 'lead_status:"Not Interested" sort:updated',
            "is_shared": True,
        },
    ]

    # Refresh views list after deletions
    resp = api_get("saved_search/?_type=lead")
    existing_names = {sv["name"] for sv in resp.get("data", [])}

    for view in new_views:
        if view["name"] in existing_names:
            print(f"  SKIP: view '{view['name']}' already exists")
        else:
            try:
                result = api_post("saved_search/", {
                    "name": view["name"],
                    "query": view["query"],
                    "is_shared": view["is_shared"],
                    "_type": "lead",
                })
                print(f"  CREATED view: '{view['name']}'")
            except Exception as e:
                print(f"  FAILED to create '{view['name']}': {e}")

    print("  Done.")


# ===========================================================================
# Main
# ===========================================================================

def main():
    if not API_KEY:
        print("ERROR: CLOSE_API_KEY not set in environment")
        sys.exit(1)

    print("Close CRM Migration — Scrub Squad Reorganization")
    print("=" * 60)

    # Test connection
    try:
        me = api_get("me/")
        org_name = me.get("organizations", [{}])[0].get("name", "Unknown")
        print(f"Connected to: {org_name}")
        print(f"User: {me.get('first_name')} {me.get('last_name')}")
    except Exception as e:
        print(f"Failed to connect: {e}")
        sys.exit(1)

    # Phase 1: Create statuses
    all_statuses = phase1_create_statuses()

    # Phase 2: Create custom fields
    phase2_create_custom_fields()

    # Phase 3: Migrate leads
    total = phase3_migrate_leads(all_statuses)

    # Phase 4: Delete coaching custom fields
    phase4_delete_custom_fields()

    # Phase 5: Delete old statuses
    # Refresh status list after migration
    resp = api_get("status/lead/")
    all_statuses = {s["label"]: s["id"] for s in resp["data"]}
    phase5_delete_old_statuses(all_statuses)

    # Phase 6: Update pipeline
    phase6_update_pipeline()

    # Phase 7: Smart Views
    phase7_smart_views()

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)

    # Final status count
    resp = api_get("status/lead/")
    print("\nFinal lead statuses:")
    for s in resp["data"]:
        print(f"  - {s['label']}")

    resp = api_get("custom_field/lead/")
    print(f"\nFinal custom fields ({len(resp['data'])}):")
    for f in resp["data"]:
        print(f"  - {f['name']} ({f['type']})")


if __name__ == "__main__":
    main()
