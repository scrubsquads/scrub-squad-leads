"""
Close CRM - Poll for new inbound activity (SMS + email) since last checkpoint.

Prints new inbound activities as JSON and advances the checkpoint file so
the next run only sees activity that arrived after this run. Designed to be
called every few minutes by a cron job feeding an agent.

Checkpoint file: .tmp/last_poll_checkpoint.json (gitignored, local state only)
"""
import os
import sys
import json
import base64
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("CLOSE_API_KEY", "")
BASE_URL = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(f"{API_KEY}:".encode()).decode()

CHECKPOINT_PATH = Path(__file__).resolve().parent.parent / ".tmp" / "last_poll_checkpoint.json"


def api_get(path, params=None):
    qs = ""
    if params:
        from urllib.parse import urlencode
        qs = "?" + urlencode(params)
    req = urllib.request.Request(f"{BASE_URL}/{path}{qs}", headers={"Authorization": AUTH})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def load_checkpoint():
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    # Default: only look back 1 hour on first ever run, not all history
    return {"last_seen_iso": None}


def save_checkpoint(iso):
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps({"last_seen_iso": iso}))


def main():
    if not API_KEY:
        print(json.dumps({"error": "CLOSE_API_KEY missing"}))
        return 1

    cp = load_checkpoint()
    last_seen = cp.get("last_seen_iso")

    new_items = []
    latest_seen = last_seen

    for kind, endpoint in [("sms", "activity/sms/"), ("email", "activity/email/")]:
        res = api_get(endpoint, {"_limit": 50})
        for a in res.get("data", []):
            direction = a.get("direction")
            is_inbound = direction in ("inbound", "incoming")
            if not is_inbound:
                continue
            created = a.get("date_created")
            if not created:
                continue
            if last_seen and created <= last_seen:
                continue
            item = {
                "kind": kind,
                "lead_id": a.get("lead_id"),
                "contact_id": a.get("contact_id"),
                "date_created": created,
                "activity_id": a.get("id"),
            }
            if kind == "sms":
                item["text"] = a.get("text")
                item["from"] = a.get("remote_phone")
            else:
                item["subject"] = a.get("subject")
                item["from"] = a.get("sender")
                item["body_preview"] = (a.get("body_text") or "")[:500]
            new_items.append(item)
            if not latest_seen or created > latest_seen:
                latest_seen = created

    new_items.sort(key=lambda x: x["date_created"])

    if latest_seen:
        save_checkpoint(latest_seen)
    elif not last_seen:
        # First run, nothing new, set checkpoint to now so we don't replay all history
        save_checkpoint(datetime.now(timezone.utc).isoformat())

    print(json.dumps({"new_count": len(new_items), "items": new_items}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
