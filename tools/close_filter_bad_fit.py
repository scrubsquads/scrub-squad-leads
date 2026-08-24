"""
Close CRM - Filter Bad-Fit Leads from "New Lead" Status

Identifies leads in the "New Lead" status that match a blocklist of national
chains and enterprise-size companies (which typically have in-house cleaning
staff and don't convert for small commercial cleaning operators).

DRY RUN by default - shows matches but does not modify Close.
Pass --execute to actually move matched leads to "In-House" status and
unsubscribe them from any active email sequences.

Only touches leads in "New Lead" status. Anything you've already worked
(Contacted, Follow Up, Hot Lead, Walkthrough Scheduled, etc.) is untouched.
"""
import os
import re
import sys
import json
import time
import base64
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

CLOSE_API_KEY = os.environ.get("CLOSE_API_KEY", "")
if not CLOSE_API_KEY:
    sys.exit("ERROR: CLOSE_API_KEY not set in .env")

BASE_URL = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(f"{CLOSE_API_KEY}:".encode()).decode()

SOURCE_STATUS = "New Lead"
TARGET_STATUS_LABEL = "In-House"

# ---------------------------------------------------------------------------
# Blocklist - exact-word matches (case-insensitive)
# Each entry becomes a regex with word boundaries to avoid false positives.
# ---------------------------------------------------------------------------
BLOCKLIST = {
    "Banks (national)": [
        "Truist", "Wells Fargo", "Chase Bank", "JPMorgan", "Bank of America",
        "BofA", "PNC Bank", "Citibank", "Citigroup", "Citi Bank",
        "U.S. Bank", "US Bank",
        "Capital One", "TD Bank", "Regions Bank", "Fifth Third", "BB&T",
        "SunTrust", "HSBC", "Santander", "BMO Harris", "Ally Bank",
        "Bank of the West", "Comerica", "KeyBank", "M&T Bank", "Huntington Bank",
        # Note: bare "Citi" intentionally excluded - caught churches like "Citi Church".
    ],
    "Hotel chains": [
        "Marriott", "Hilton", "Hyatt", "IHG", "Holiday Inn", "Crowne Plaza",
        "Virgin Hotels", "Four Seasons", "Ritz-Carlton", "Ritz Carlton",
        "W Hotel", "Westin", "Sheraton", "Loews", "Kimpton", "Wyndham",
        "Best Western", "La Quinta", "Hampton Inn", "Courtyard", "Embassy Suites",
        "DoubleTree", "Hilton Garden", "Residence Inn", "Fairfield Inn",
        "Springhill Suites", "TownePlace", "Aloft", "Element Hotel",
        "Renaissance Hotel", "JW Marriott", "Edition Hotel", "St. Regis",
        "Park Hyatt", "Grand Hyatt", "Andaz", "Conrad Hotel", "Waldorf Astoria",
        "Mandarin Oriental", "Fontainebleau", "1 Hotel", "EAST Miami",
        "SLS Hotel", "Mondrian", "Standard Hotel", "Soho House",
    ],
    "Medical systems": [
        "HCA Healthcare", "HCA Florida", "Baptist Health", "Cleveland Clinic",
        "Jackson Health", "Jackson Memorial", "Memorial Healthcare",
        "Tenet Healthcare", "Mount Sinai", "Nicklaus Children", "Kaiser",
        "Aspen Dental", "Heartland Dental", "Pacific Dental",
        "Sage Dental", "MyEyeDr", "America's Best", "Banfield Pet",
        "VCA Animal", "BluePearl",
    ],
    "Property mgmt (national)": [
        "Greystar", "Lincoln Property", "Cushman & Wakefield", "Cushman and Wakefield",
        "JLL", "CBRE", "Colliers", "Newmark", "Avison Young", "Camden Property",
        "AvalonBay", "Related Group", "Equity Residential", "Mid-America Apartment",
        "Essex Property", "UDR Inc", "Highwoods Properties", "Brookfield Property",
    ],
    "Big-box retail / chains": [
        "Amazon", "Walmart", "Costco", "Target Corp", "Home Depot", "Lowe's",
        "Publix", "Whole Foods", "Trader Joe's", "Aldi", "Sprouts Farmers",
        "Winn-Dixie", "CVS Pharmacy", "Walgreens", "Rite Aid",
        "Starbucks", "McDonald's", "Chick-fil-A", "Burger King", "Wendy's",
        "Subway", "Chipotle", "Panera", "Dunkin", "Taco Bell", "KFC",
        "Pizza Hut", "Domino's", "Olive Garden", "Red Lobster", "Applebee's",
        "Chili's", "Outback Steakhouse", "Cheesecake Factory",
    ],
    "Telecom / insurance / logistics": [
        "FedEx", "UPS Store", "United Parcel", "DHL", "USPS",
        "State Farm", "Allstate", "Geico", "Progressive Insurance",
        "Liberty Mutual", "Farmers Insurance", "Nationwide Insurance",
        "AT&T", "Verizon", "T-Mobile", "Sprint", "Comcast", "Xfinity",
        "Spectrum",
    ],
    "Enterprise indicators (suffix patterns)": [
        # "Worldwide" and "Corporation" removed - too broad, caught small locals
        # like "Worldwide Draperies" and "Cary Construction Corporation".
        # Keep only strong tells.
        "Holdings LLC", "Holdings, LLC", "Holdings Inc", "Holdings, Inc",
        "Enterprises Inc", "Enterprises, Inc",
    ],
}

# Compile regex patterns (word boundaries, case-insensitive)
COMPILED_PATTERNS = []
for category, names in BLOCKLIST.items():
    for name in names:
        # Escape regex special chars in name, then add word boundaries
        # Word boundary works on alphanumeric, so & and ' need different handling
        escaped = re.escape(name)
        pattern = re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)
        COMPILED_PATTERNS.append((pattern, category, name))


def matches_blocklist(company_name):
    """Return (category, matched_term) if name matches blocklist, else None."""
    if not company_name:
        return None
    for pattern, category, term in COMPILED_PATTERNS:
        if pattern.search(company_name):
            return (category, term)
    return None


# ---------------------------------------------------------------------------
# Close API helpers
# ---------------------------------------------------------------------------
def close_request(method, path, body=None, retries=3):
    """HTTP request with retry/backoff. Never logs body content."""
    url = BASE_URL + path
    data = json.dumps(body).encode() if body else None
    headers = {"Authorization": AUTH, "Content-Type": "application/json"}

    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                wait = 2 ** attempt
                print(f"  Rate limit, waiting {wait}s...")
                time.sleep(wait)
                continue
            if 500 <= e.code < 600:
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise last_err


def get_status_id(label):
    """Look up status ID by label."""
    r = close_request("GET", "/status/lead/")
    for s in r.get("data", []):
        if s["label"] == label:
            return s["id"]
    raise RuntimeError(f"Status '{label}' not found")


def fetch_all_new_leads(status_label):
    """Fetch every lead in the given status (paginated)."""
    leads = []
    skip = 0
    page_size = 100
    q = urllib.parse.quote(f'lead_status:"{status_label}"')
    while True:
        path = f"/lead/?query={q}&_skip={skip}&_limit={page_size}"
        r = close_request("GET", path)
        batch = r.get("data", [])
        leads.extend(batch)
        if not r.get("has_more") or not batch:
            break
        skip += page_size
        print(f"  Fetched {len(leads)} so far...")
    return leads


def get_active_subscriptions(lead_id):
    """Return list of active sequence subscription IDs for a lead."""
    r = close_request("GET", f"/sequence_subscription/?lead_id={lead_id}")
    return [s["id"] for s in r.get("data", []) if s.get("status") == "active"]


def pause_subscription(sub_id):
    return close_request(
        "PUT",
        f"/sequence_subscription/{sub_id}/",
        body={"status": "paused"},
    )


def update_lead_status(lead_id, status_id):
    return close_request("PUT", f"/lead/{lead_id}/", body={"status_id": status_id})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(execute=False):
    print("=" * 70)
    print("Close CRM - Bad-Fit Lead Filter")
    print(f"Mode: {'EXECUTE (will modify Close)' if execute else 'DRY RUN (no changes)'}")
    print("=" * 70)

    print(f"\nFetching leads in '{SOURCE_STATUS}' status...")
    leads = fetch_all_new_leads(SOURCE_STATUS)
    print(f"  Total New Lead status leads: {len(leads)}")

    matches = []
    for lead in leads:
        name = lead.get("display_name") or lead.get("name") or ""
        m = matches_blocklist(name)
        if m:
            matches.append({
                "id": lead["id"],
                "name": name,
                "category": m[0],
                "matched_term": m[1],
            })

    print(f"\nBlocklist matches: {len(matches)} / {len(leads)}")

    if not matches:
        print("\nNo bad-fit leads found. Nothing to do.")
        return

    # Group by category for readability
    print("\n" + "=" * 70)
    print("MATCHES BY CATEGORY")
    print("=" * 70)
    by_cat = {}
    for m in matches:
        by_cat.setdefault(m["category"], []).append(m)

    for cat, items in sorted(by_cat.items()):
        print(f"\n[{cat}] - {len(items)} leads")
        for m in items:
            print(f"  - {m['name']}  (matched: '{m['matched_term']}')")

    # Save full list to CSV for review
    csv_path = Path(__file__).resolve().parent.parent / ".tmp" / "close_bad_fit_matches.csv"
    csv_path.parent.mkdir(exist_ok=True)
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("lead_id,company_name,category,matched_term\n")
        for m in matches:
            safe_name = m["name"].replace('"', '""')
            f.write(f'{m["id"]},"{safe_name}",{m["category"]},{m["matched_term"]}\n')
    print(f"\nFull list saved to: {csv_path}")

    if not execute:
        print("\n" + "=" * 70)
        print("DRY RUN complete. Review the list above.")
        print("To actually move these to 'In-House' status, run:")
        print("  py tools/close_filter_bad_fit.py --execute")
        print("=" * 70)
        return

    # EXECUTE mode
    print(f"\nResolving target status ID for '{TARGET_STATUS_LABEL}'...")
    target_status_id = get_status_id(TARGET_STATUS_LABEL)

    print(f"\nMoving {len(matches)} leads to '{TARGET_STATUS_LABEL}' and unsubscribing from sequences...")
    moved = 0
    paused = 0
    errors = 0
    for i, m in enumerate(matches, 1):
        try:
            subs = get_active_subscriptions(m["id"])
            for sub_id in subs:
                pause_subscription(sub_id)
                paused += 1
            update_lead_status(m["id"], target_status_id)
            moved += 1
            if i % 10 == 0:
                print(f"  Progress: {i}/{len(matches)} ({moved} moved, {paused} sequence subs paused)")
        except Exception as e:
            errors += 1
            print(f"  ERROR on {m['name']}: {e}")

    print("\n" + "=" * 70)
    print(f"DONE. Moved: {moved} | Sequence subs paused: {paused} | Errors: {errors}")
    print("=" * 70)


if __name__ == "__main__":
    execute = "--execute" in sys.argv
    main(execute=execute)
