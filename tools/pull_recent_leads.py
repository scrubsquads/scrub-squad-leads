"""
Pull the most recently created leads (actual new inbound leads, not the whole backlog)
and analyze fit for Scrub Squad (South Florida commercial cleaning).
"""
import os, sys, json, base64, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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

def api_get(path, params=None):
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": AUTH})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# Pull New Lead status, sorted by created date, most recent first
q = 'lead_status:"New Lead" sort:-created'
leads = []
skip = 0
while True:
    data = api_get("/lead/", {"query": q, "_skip": skip, "_limit": 100})
    leads.extend(data.get("data", []))
    if not data.get("has_more") or len(leads) >= 300:
        break
    skip += 100

# Take the most recent 30 by date_created
def parse_dt(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

leads.sort(key=lambda l: parse_dt(l.get("date_created", "")), reverse=True)
recent = leads[:30]

out = []
for l in recent:
    out.append({
        "id": l.get("id"),
        "name": l.get("display_name") or l.get("name"),
        "date_created": l.get("date_created"),
        "url": l.get("url"),
        "addresses": l.get("addresses"),
        "custom": {k: v for k, v in l.items() if k.startswith("custom.")},
        "contacts": [
            {"name": c.get("name"), "emails": [e.get("email") for e in c.get("emails", [])], "phones": [p.get("phone") for p in c.get("phones", [])]}
            for c in l.get("contacts", [])
        ],
    })

with open(Path(__file__).resolve().parent.parent / ".tmp" / "recent_leads.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)

print(f"Pulled {len(out)} most recent New Lead status leads (out of {len(leads)} scanned).")
for l in out[:30]:
    addr = l["addresses"][0] if l.get("addresses") else {}
    city = addr.get("city", "")
    state = addr.get("state", "")
    print(f"- {l['name']}  [{l['date_created']}]  {city}, {state}")
