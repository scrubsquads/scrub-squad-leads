"""
Analyze Close 'New Lead' status to identify bad-fit patterns.

Pulls all New Lead status leads with custom fields and reports:
- Company size distribution (how many big-co leads are slipping through)
- Top repeating company-name prefixes (multi-location chains we missed)
- Industry breakdown
- Leads missing Company Size (Apollo enrichment didn't run)
"""
import os
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

CLOSE_API_KEY = os.environ["CLOSE_API_KEY"]
AUTH = "Basic " + base64.b64encode(f"{CLOSE_API_KEY}:".encode()).decode()
BASE_URL = "https://api.close.com/api/v1"

CF_COMPANY_SIZE = "cf_Rdue2GgBUEd5TOZKoW4ZPkaqu7OHZkt30M7vUwuA3Go"
CF_INDUSTRY = "cf_NWqDARosFM4mCEt4y0VwYWNLT0zzjgKK7zdozO5V3zw"


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

    # --- Company size distribution ---
    size_buckets = Counter()
    sizes_raw = []
    for lead in leads:
        size = lead.get(f"custom.{CF_COMPANY_SIZE}")
        if size is None or size == "":
            size_buckets["UNKNOWN (no Apollo data)"] += 1
        else:
            try:
                n = int(float(size))
                sizes_raw.append(n)
                if n <= 10:
                    size_buckets["1-10"] += 1
                elif n <= 50:
                    size_buckets["11-50"] += 1
                elif n <= 200:
                    size_buckets["51-200"] += 1
                elif n <= 500:
                    size_buckets["201-500"] += 1
                elif n <= 1000:
                    size_buckets["501-1000"] += 1
                else:
                    size_buckets["1001+"] += 1
            except (ValueError, TypeError):
                size_buckets["UNKNOWN (parse error)"] += 1

    print("=" * 70)
    print("COMPANY SIZE DISTRIBUTION")
    print("=" * 70)
    order = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001+",
             "UNKNOWN (no Apollo data)", "UNKNOWN (parse error)"]
    for bucket in order:
        n = size_buckets.get(bucket, 0)
        if n:
            pct = 100 * n / len(leads)
            bar = "#" * int(pct / 2)
            print(f"  {bucket:30} {n:4}  ({pct:5.1f}%)  {bar}")

    # --- Companies over 50 employees (your in-house staff threshold) ---
    big_cos = []
    for lead in leads:
        size = lead.get(f"custom.{CF_COMPANY_SIZE}")
        if size is None or size == "":
            continue
        try:
            n = int(float(size))
            if n > 50:
                big_cos.append((n, lead.get("display_name") or lead.get("name", "")))
        except (ValueError, TypeError):
            continue
    big_cos.sort(reverse=True)

    print("\n" + "=" * 70)
    print(f"COMPANIES > 50 EMPLOYEES (likely have in-house cleaning) — {len(big_cos)} leads")
    print("=" * 70)
    for size, name in big_cos[:40]:
        print(f"  {size:>6} employees  {name}")
    if len(big_cos) > 40:
        print(f"  ... and {len(big_cos) - 40} more")

    # --- Repeating name prefixes (multi-location chains we missed) ---
    print("\n" + "=" * 70)
    print("REPEATING COMPANY-NAME PREFIXES (multi-location chains we missed)")
    print("=" * 70)
    prefixes = Counter()
    name_examples = {}
    for lead in leads:
        name = (lead.get("display_name") or lead.get("name") or "").strip()
        if not name:
            continue
        # First 2 words as prefix
        words = name.split()
        if len(words) >= 2:
            prefix = " ".join(words[:2])
            prefixes[prefix] += 1
            name_examples.setdefault(prefix, []).append(name)
    repeating = [(p, c) for p, c in prefixes.items() if c >= 3]
    repeating.sort(key=lambda x: -x[1])
    for prefix, count in repeating[:25]:
        examples = name_examples[prefix][:3]
        print(f"  {count}x  '{prefix}...'  e.g. {', '.join(examples)}")

    # --- Industry breakdown ---
    print("\n" + "=" * 70)
    print("INDUSTRY BREAKDOWN")
    print("=" * 70)
    industries = Counter()
    for lead in leads:
        ind = lead.get(f"custom.{CF_INDUSTRY}") or "UNKNOWN"
        industries[ind] += 1
    for ind, n in industries.most_common():
        pct = 100 * n / len(leads)
        print(f"  {ind:40} {n:4}  ({pct:5.1f}%)")

    # --- Summary stats ---
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    over_50 = len(big_cos)
    has_size = len(sizes_raw)
    no_size = len(leads) - has_size
    print(f"  Total New Lead status leads: {len(leads)}")
    print(f"  Have Apollo employee count: {has_size} ({100*has_size/len(leads):.0f}%)")
    print(f"  Missing employee count: {no_size} ({100*no_size/len(leads):.0f}%)")
    print(f"  Over 50 employees (target for In-House move): {over_50}")
    print()
    print("  Filter recommendation:")
    print(f"  - Auto-move {over_50} leads with >50 employees to In-House")
    print(f"  - Review {no_size} leads with no Apollo data separately")


if __name__ == "__main__":
    main()
