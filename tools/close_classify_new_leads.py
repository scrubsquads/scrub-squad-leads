"""
Classify all 'New Lead' status leads as DEFINITE_BAD / SUSPECTED_BAD / KEEP
using expanded heuristics: name patterns, franchise indicators, multi-location
chains, government, large institutions.

Outputs a CSV for review and prints summary counts.

Pass --execute to actually move DEFINITE_BAD leads to "In-House" status and
pause their active email sequence subscriptions. Default is dry-run only.
"""
import time
import os
import re
import sys
import json
import base64
import urllib.parse
import urllib.request
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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

# ---------------------------------------------------------------------------
# Definite-bad patterns - things that are clearly too big for a small operator
# ---------------------------------------------------------------------------
DEFINITE_BAD_PATTERNS = [
    # National banks
    (r"\b(Truist|Wells Fargo|Chase Bank|JPMorgan|Bank of America|BofA|PNC Bank|"
     r"Citibank|Citigroup|U\.?S\.? Bank|Capital One|TD Bank|Regions Bank|"
     r"Fifth Third|BB&T|SunTrust|HSBC|Santander|BMO Harris|Ally Bank|Comerica|"
     r"KeyBank|M&T Bank|Huntington Bank)\b", "National bank"),

    # Hotel chains - exhaustive
    (r"\b(Marriott|Hilton|Hyatt|IHG|Holiday Inn|Crowne Plaza|Virgin Hotels|"
     r"Four Seasons|Ritz[ -]Carlton|W Hotel|Westin|Sheraton|Loews|Kimpton|"
     r"Wyndham|Best Western|La Quinta|Hampton Inn|Courtyard|Embassy Suites|"
     r"DoubleTree|Hilton Garden|Residence Inn|Fairfield Inn|Springhill Suites|"
     r"TownePlace|Aloft|Element Hotel|Renaissance Hotel|JW Marriott|"
     r"Edition Hotel|St\.? Regis|Park Hyatt|Grand Hyatt|Andaz|Conrad Hotel|"
     r"Waldorf Astoria|Mandarin Oriental|Fontainebleau|SLS Hotel|Mondrian|"
     r"Standard Hotel|Soho House)\b", "Hotel chain"),

    # Franchise / "by [Brand]" indicators
    (r"\bby (Wyndham|IHG|Marriott|Hilton|Hyatt|Choice Hotels|Best Western|"
     r"Radisson|InterContinental)\b", "Hotel franchise"),

    # Universities & big colleges
    (r"\b(University of |[A-Z][a-z]+ University|Florida International University|"
     r"FIU|Miami Dade College|Broward College|Nova Southeastern|St\.? Thomas University|"
     r"Barry University|Lynn University|Florida Memorial|Carlos Albizu)\b",
     "University / large college"),

    # Big medical systems
    (r"\b(HCA Healthcare|HCA Florida|Baptist Health|Cleveland Clinic|"
     r"Jackson Health|Jackson Memorial|Memorial Healthcare|Tenet Healthcare|"
     r"Mount Sinai|Nicklaus Children|Kaiser|Larkin Community Hospital|"
     r"Doctors Hospital|Mercy Hospital|Aventura Hospital|Kendall Regional|"
     r"Hialeah Hospital|Westside Regional|Northwest Medical|Coral Gables Hospital|"
     r"South Miami Hospital|Homestead Hospital|Health System|"
     r"Community Medical Center|Community Health Center|Community & Family Health)\b",
     "Big medical system"),

    # Dental/optical/vet chains
    (r"\b(Aspen Dental|Heartland Dental|Pacific Dental|Sage Dental|MyEyeDr|"
     r"America's Best|Banfield Pet|VCA Animal|BluePearl|Affordable Dentures|"
     r"Dental Care Alliance|Smile Direct|Western Dental|Coast Dental)\b",
     "Dental/vet/optical chain"),

    # National property mgmt / REIT
    (r"\b(Greystar|Lincoln Property|Cushman & Wakefield|Cushman and Wakefield|"
     r"JLL|CBRE|Colliers|Newmark|Avison Young|Camden Property|AvalonBay|"
     r"Equity Residential|Mid-America Apartment|Essex Property|UDR Inc|"
     r"Highwoods Properties|Brookfield Property|Related Group|Crescent Heights|"
     r"Lennar|Pulte|D\.?R\.? Horton|Toll Brothers|KB Home)\b",
     "National prop mgmt / homebuilder"),

    # Big-box / national chains
    (r"\b(Amazon|Walmart|Costco|Target Corp|Home Depot|Lowe's|Publix|Whole Foods|"
     r"Trader Joe's|Aldi|Sprouts Farmers|Winn-Dixie|Fresh Market|"
     r"CVS Pharmacy|Walgreens|Rite Aid|Starbucks|McDonald's|Chick-fil-A|"
     r"Burger King|Wendy's|Subway|Chipotle|Panera|Dunkin|Taco Bell|KFC|"
     r"Pizza Hut|Domino's|Olive Garden|Red Lobster|Applebee's|Chili's|"
     r"Outback Steakhouse|Cheesecake Factory|TJ Maxx|Marshalls|Ross|Macy's|"
     r"Nordstrom|Bloomingdale's|Best Buy|Office Depot|Staples|PetSmart|"
     r"Petco|Five Below|Dollar Tree|Dollar General|Family Dollar|"
     r"Bed Bath|Burlington|AutoZone|Advance Auto|O'Reilly Auto|NAPA)\b",
     "Big-box / national chain"),

    # Telecom / insurance / logistics
    (r"\b(FedEx|United Parcel Service|UPS Store|DHL|USPS|State Farm|Allstate|"
     r"Geico|Progressive Insurance|Liberty Mutual|Farmers Insurance|"
     r"Nationwide Insurance|AT&T|Verizon|T-Mobile|Sprint|Comcast|Xfinity|"
     r"Spectrum|Cox Communications|DirecTV|Dish Network)\b",
     "Telecom / insurance / logistics"),

    # Government / public
    (r"\b(Miami-Dade County|Broward County|City of Miami|City of Homestead|"
     r"City of Coral Gables|City of Hialeah|FDOT|Florida Department|"
     r"U\.?S\.? Postal|Social Security|IRS|Department of |Public Schools|"
     r"County Public|Miami Dade Public)\b", "Government"),

    # Coworking chains
    (r"\b(WeWork|Regus|Quest Workspaces|Industrious|Spaces Coworking|"
     r"Office Evolution|Premier Workspaces|Pipeline Workspaces|Cambridge Innovation)\b",
     "Coworking chain"),

    # Auto / car dealer groups (national, NOT individual local dealers)
    (r"\b(AutoNation|CarMax|Carvana|Sonic Automotive|Penske Automotive|"
     r"Group 1 Automotive|Asbury Automotive|Lithia Motors)\b",
     "National auto group"),

    # Defense / large industrial
    (r"\b(Lockheed Martin|Northrop Grumman|Raytheon|Boeing|General Dynamics|"
     r"L3Harris|Honeywell|3M Company|GE Aerospace|Pratt & Whitney)\b",
     "Defense / large industrial"),

    # Large suffix patterns
    (r"\b(Holdings,? LLC|Holdings,? Inc|Enterprises,? Inc)\b", "Holdings entity"),
]

# ---------------------------------------------------------------------------
# Suspected-bad patterns - worth review but not certain
# ---------------------------------------------------------------------------
SUSPECTED_BAD_PATTERNS = [
    (r"\b(Foundation|Institute|Center for|Centers for)\b",
     "Possibly large institution"),
    (r"\b(Group LLC|Group, LLC|Group Inc|Group, Inc)\b", "Group entity"),
    (r"\b(Medical Center|Medical Group|Health Services|Healthcare Services)\b",
     "Possibly multi-location medical"),
    (r"\b(Apartments|Apartment Homes|Residences)\b", "Large residential complex"),
]

COMPILED_DEFINITE = [(re.compile(p, re.IGNORECASE), reason) for p, reason in DEFINITE_BAD_PATTERNS]
COMPILED_SUSPECTED = [(re.compile(p, re.IGNORECASE), reason) for p, reason in SUSPECTED_BAD_PATTERNS]


def classify(name):
    """Return (verdict, reason) where verdict is 'DEFINITE_BAD', 'SUSPECTED_BAD', or 'KEEP'."""
    if not name:
        return "KEEP", ""
    for pattern, reason in COMPILED_DEFINITE:
        m = pattern.search(name)
        if m:
            return "DEFINITE_BAD", f"{reason}: '{m.group(0)}'"
    for pattern, reason in COMPILED_SUSPECTED:
        m = pattern.search(name)
        if m:
            return "SUSPECTED_BAD", f"{reason}: '{m.group(0)}'"
    return "KEEP", ""


def get_status_id(label):
    req = urllib.request.Request(f"{BASE_URL}/status/lead/", headers={"Authorization": AUTH})
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    for s in data.get("data", []):
        if s["label"] == label:
            return s["id"]
    raise RuntimeError(f"Status '{label}' not found")


def get_active_subscriptions(lead_id):
    req = urllib.request.Request(
        f"{BASE_URL}/sequence_subscription/?lead_id={lead_id}",
        headers={"Authorization": AUTH},
    )
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    return [s["id"] for s in data.get("data", []) if s.get("status") == "active"]


def pause_subscription(sub_id):
    body = json.dumps({"status": "paused"}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/sequence_subscription/{sub_id}/",
        data=body,
        headers={"Authorization": AUTH, "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def update_lead_status(lead_id, status_id):
    body = json.dumps({"status_id": status_id}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/lead/{lead_id}/",
        data=body,
        headers={"Authorization": AUTH, "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def fetch_all_new_leads():
    leads = []
    skip = 0
    q = urllib.parse.quote('lead_status:"New Lead"')
    while True:
        req = urllib.request.Request(
            f"{BASE_URL}/lead/?query={q}&_skip={skip}&_limit=100",
            headers={"Authorization": AUTH},
        )
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        leads.extend(data.get("data", []))
        if not data.get("has_more"):
            break
        skip += 100
    return leads


def main():
    print("Fetching all 'New Lead' status leads...")
    leads = fetch_all_new_leads()
    print(f"Total: {len(leads)}\n")

    results = []
    for lead in leads:
        name = (lead.get("display_name") or lead.get("name") or "").strip()
        verdict, reason = classify(name)
        results.append({
            "id": lead["id"],
            "name": name,
            "verdict": verdict,
            "reason": reason,
        })

    counts = Counter(r["verdict"] for r in results)
    print("=" * 70)
    print("CLASSIFICATION SUMMARY")
    print("=" * 70)
    for v in ["DEFINITE_BAD", "SUSPECTED_BAD", "KEEP"]:
        n = counts.get(v, 0)
        pct = 100 * n / len(leads) if leads else 0
        print(f"  {v:18} {n:4}  ({pct:5.1f}%)")

    # Show definite bads grouped by reason
    print("\n" + "=" * 70)
    print("DEFINITE_BAD - by reason")
    print("=" * 70)
    by_reason_def = {}
    for r in results:
        if r["verdict"] == "DEFINITE_BAD":
            reason_key = r["reason"].split(":")[0]
            by_reason_def.setdefault(reason_key, []).append(r["name"])
    for reason, names in sorted(by_reason_def.items(), key=lambda x: -len(x[1])):
        print(f"\n[{reason}] - {len(names)} leads")
        for n in names[:8]:
            print(f"  - {n}")
        if len(names) > 8:
            print(f"  ... and {len(names) - 8} more")

    # Show suspected bads (for manual review)
    print("\n" + "=" * 70)
    print("SUSPECTED_BAD - needs your eyeball")
    print("=" * 70)
    suspected = [r for r in results if r["verdict"] == "SUSPECTED_BAD"]
    for r in suspected:
        print(f"  - {r['name']}   [{r['reason']}]")

    # Write CSV for review
    csv_path = Path(__file__).resolve().parent.parent / ".tmp" / "close_classification.csv"
    csv_path.parent.mkdir(exist_ok=True)
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("lead_id,company_name,verdict,reason\n")
        for r in results:
            safe = r["name"].replace('"', '""')
            safe_reason = r["reason"].replace('"', '""')
            f.write(f'{r["id"]},"{safe}",{r["verdict"]},"{safe_reason}"\n')
    print(f"\nFull CSV: {csv_path}")
    print(f"\nKEEP count: {counts.get('KEEP', 0)} leads (these stay in New Lead)")

    if not EXECUTE:
        print("\n" + "=" * 70)
        print("DRY RUN. To move DEFINITE_BAD to In-House, run:")
        print("  py tools/close_classify_new_leads.py --execute")
        print("=" * 70)
        return

    # EXECUTE: move DEFINITE_BAD to In-House
    to_move = [r for r in results if r["verdict"] == "DEFINITE_BAD"]
    if not to_move:
        print("\nNothing to move.")
        return

    print("\n" + "=" * 70)
    print(f"EXECUTING: moving {len(to_move)} DEFINITE_BAD leads to In-House")
    print("=" * 70)
    target_id = get_status_id("In-House")
    moved = paused = errors = 0
    for i, r in enumerate(to_move, 1):
        try:
            subs = get_active_subscriptions(r["id"])
            for sub_id in subs:
                pause_subscription(sub_id)
                paused += 1
            update_lead_status(r["id"], target_id)
            moved += 1
            if i % 10 == 0 or i == len(to_move):
                print(f"  Progress: {i}/{len(to_move)} ({moved} moved, {paused} subs paused)")
            time.sleep(0.1)  # gentle on the API
        except Exception as e:
            errors += 1
            print(f"  ERROR on '{r['name']}': {e}")

    print("\n" + "=" * 70)
    print(f"DONE. Moved: {moved} | Sequence subs paused: {paused} | Errors: {errors}")
    print("=" * 70)


if __name__ == "__main__":
    EXECUTE = "--execute" in sys.argv
    main()
