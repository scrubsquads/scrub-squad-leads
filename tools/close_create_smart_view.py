"""
Create the 'Primary New Leads' Smart View in Close.

Filters leads in 'New Lead' status whose Industry matches one of the
primary target categories (property management, apartment buildings,
construction/contractors, AirBnb mgmt).

Safe to re-run: if a Smart View with the same name exists, prints its
current query and exits without creating a duplicate.
"""
import os
import sys
import json
import base64
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

AUTH = "Basic " + base64.b64encode(f"{os.environ['CLOSE_API_KEY']}:".encode()).decode()
BASE_URL = "https://api.close.com/api/v1"

SMART_VIEW_NAME = "Primary New Leads"

# Industries that count as "primary targets" for a small cleaning operator:
# recurring contracts, multi-unit physical locations, owner-decided buying.
PRIMARY_INDUSTRIES = [
    "Property Management",
    "Apartment Building",
    "Construction",
    "AirBnb",
]


def close_get(path):
    req = urllib.request.Request(f"{BASE_URL}/{path}", headers={"Authorization": AUTH})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def close_post(path, body):
    req = urllib.request.Request(
        f"{BASE_URL}/{path}",
        data=json.dumps(body).encode(),
        headers={"Authorization": AUTH, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body_text[:500]}")
        raise


def build_query_string():
    """Human-readable query string for previewing match count via lead search."""
    industry_clause = " or ".join(
        f'"Industry":"{ind}"' for ind in PRIMARY_INDUSTRIES
    )
    return f'lead_status:"New Lead" and ({industry_clause})'


def get_status_id(label):
    data = close_get("status/lead/")
    for s in data.get("data", []):
        if s["label"] == label:
            return s["id"]
    raise RuntimeError(f"Status '{label}' not found")


def get_industry_custom_field_id():
    data = close_get("custom_field/lead/")
    for f in data.get("data", []):
        if f["name"] == "Industry":
            return f["id"]
    raise RuntimeError("Industry custom field not found")


def build_structured_query(new_lead_status_id, industry_cf_id, industries):
    """Build Close's structured s_query tree.

    Top-level AND:
      - object_type = lead
      - AND:
          - status_id = New Lead
          - OR of one term-match per industry value
    """
    industry_conditions = [
        {
            "condition": {"type": "term", "values": [ind]},
            "field": {
                "type": "custom_field",
                "custom_field_id": industry_cf_id,
            },
            "negate": False,
            "type": "field_condition",
        }
        for ind in industries
    ]

    return {
        "query": {
            "negate": False,
            "type": "and",
            "queries": [
                {"negate": False, "object_type": "lead", "type": "object_type"},
                {
                    "negate": False,
                    "type": "and",
                    "queries": [
                        {
                            "condition": {
                                "object_ids": [new_lead_status_id],
                                "reference_type": "status.lead",
                                "type": "reference",
                            },
                            "field": {
                                "field_name": "status_id",
                                "object_type": "lead",
                                "type": "regular_field",
                            },
                            "negate": False,
                            "type": "field_condition",
                        },
                        {
                            "negate": False,
                            "type": "or",
                            "queries": industry_conditions,
                        },
                    ],
                },
            ],
        },
        "results_limit": None,
        "sort": [],
    }


def find_existing(name):
    """Return existing saved_search dict if one with this name exists."""
    data = close_get("saved_search/")
    for sv in data.get("data", []):
        if sv.get("name") == name:
            return sv
    return None


def count_matching_leads(query):
    """Run the query against the lead search endpoint to confirm match count."""
    q = urllib.parse.quote(query)
    # Use _limit=1 just to see total_results; we don't need the data
    data = close_get(f"lead/?query={q}&_limit=1")
    return data.get("total_results", 0)


def main():
    query_str = build_query_string()
    print(f"Smart View name: {SMART_VIEW_NAME}")
    print(f"Preview query: {query_str}\n")

    # Sanity check: how many leads will it match right now?
    print("Counting matching leads...")
    n = count_matching_leads(query_str)
    print(f"  -> {n} leads currently match this filter\n")

    existing = find_existing(SMART_VIEW_NAME)
    if existing:
        print(f"Smart View '{SMART_VIEW_NAME}' already exists (id: {existing['id']})")
        print("Skipping creation.")
        return

    print("Looking up status ID and Industry custom field ID...")
    new_lead_status_id = get_status_id("New Lead")
    industry_cf_id = get_industry_custom_field_id()
    print(f"  New Lead status: {new_lead_status_id}")
    print(f"  Industry field:  {industry_cf_id}\n")

    s_query = build_structured_query(new_lead_status_id, industry_cf_id, PRIMARY_INDUSTRIES)

    print(f"Creating Smart View '{SMART_VIEW_NAME}'...")
    result = close_post("saved_search/", {
        "name": SMART_VIEW_NAME,
        "type": "lead",
        "s_query": s_query,
    })
    print(f"  Created (id: {result.get('id', '?')})")
    print(f"\nDone. Open Close -> Leads -> '{SMART_VIEW_NAME}' to see your {n} primary targets.")


if __name__ == "__main__":
    main()
