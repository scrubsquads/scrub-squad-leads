"""
Assign a Business Line (VIC / SCRUB / BOTH) to every lead in Close.

WHY
---
Two businesses share one Close org with nothing separating them: no field,
no VIC sequences, and a "Veteran Interior Construction" smart view that is
really just an import filter containing cleaning prospects. Campaigns cannot
be split until every lead says which business owns it.

MODEL
-----
VIC (Veteran Interior Construction) sells framing & drywall subcontracting to
general contractors, builders and developers.
Scrub Squad sells commercial cleaning to property managers, facility managers,
HOAs and building owners - including post-construction cleanup, which is why
a GC is a prospect for BOTH.

  general contractor / builder / developer -> BOTH   (VIC approaches first)
  generic "X Construction" (unclear)       -> BOTH   (flagged for review)
  specialty trade sub (concrete, roofing)  -> SCRUB  (a VIC peer, not a buyer)
  everything else                          -> SCRUB

Firms doing drywall/framing/interior build-out are VIC COMPETITORS and are
flagged separately - they should never receive VIC outreach.

SAFETY
------
Dry run is the default and writes nothing. --apply creates the custom field
if missing and sets values. Review .tmp/business_line_plan.csv first.
"""
import argparse
import base64
import collections
import csv
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists() and not os.environ.get("GITHUB_ACTIONS"):
    for _l in _env.read_text(encoding="utf-8").splitlines():
        _s = _l.strip()
        if _s and not _s.startswith("#") and "=" in _s:
            _k, _v = _s.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).resolve().parent))
from close_classify_new_leads import classify  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(
    f"{os.environ.get('CLOSE_API_KEY', '')}:".encode()).decode()

FIELD_NAME = "Business Line"
FIELD_CHOICES = ["VIC", "SCRUB", "BOTH"]

# Runs whole projects and hires subcontractors, so buys what VIC sells.
GC_RE = re.compile(
    r"\b(general contractor|builders?|building (group|corp|company)|"
    r"construction (group|corp|company|services|management|llc|inc)|"
    r"development|developers?|custom home|design[- ]build|contracting|"
    r"contractors?|homes?)\b", re.I)

# Peer trades: they stand alongside VIC on a job, they never hire it.
SUB_RE = re.compile(
    r"\b(concrete|roofing|roofer|paving|asphalt|electric|plumbing|hvac|"
    r"air conditioning|landscap|pool|fence|glass|window|door|flooring|"
    r"tile|paint|stucco|masonry|welding|solar|irrigation|septic|"
    r"demolition|excavat|insulation|survey|engineering|architect|"
    r"notice to owner|supply|lumber|equipment rental)\b", re.I)

# Does exactly what VIC does. Never send VIC outreach to these.
COMPETITOR_RE = re.compile(
    r"\b(drywall|framing|interior (construction|build|finish)|"
    r"metal stud|acoustical ceiling)\b", re.I)

CONSTRUCTION_HINT = re.compile(
    r"\b(construction|contractor|builder|building)\b", re.I)


def close_get(path):
    req = urllib.request.Request(
        f"{BASE_URL}/{path}",
        headers={"Authorization": AUTH, "Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{e.code} GET {path}: {e.read().decode()[:200]}")
    raise RuntimeError("retries exhausted")


def close_write(path, payload, method="POST"):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", data=body, method=method,
        headers={"Authorization": AUTH, "Content-Type": "application/json",
                 "Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(
                f"{e.code} {method} {path}: {e.read().decode()[:300]}")
    raise RuntimeError("retries exhausted")


def decide(name, industry):
    """Return (business_line, reason, is_vic_competitor)."""
    name = name or ""
    competitor = bool(COMPETITOR_RE.search(name))

    verdict, why = classify(name)
    if verdict == "DEFINITE_BAD":
        return ("SCRUB",
                f"bad-fit ({why}) - should be disqualified, not worked",
                competitor)

    ind = (industry or "").lower()
    looks_construction = ("construction" in ind
                          or bool(CONSTRUCTION_HINT.search(name)))

    if not looks_construction:
        return "SCRUB", f"industry={industry or 'n/a'}, not construction", competitor
    if competitor:
        return "SCRUB", "does drywall/framing itself - VIC competitor", True
    if SUB_RE.search(name) and not re.search(r"\bgeneral contractor\b", name, re.I):
        return "SCRUB", "specialty trade sub - VIC peer, not a buyer", competitor
    if GC_RE.search(name):
        return "BOTH", "GC / builder / developer - VIC first, then cleanup", competitor
    return "BOTH", "generic construction name - assumed GC, review", competitor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Create the field if missing and write values. "
                         "Without this, nothing is written to Close.")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=".tmp/business_line_plan.csv")
    args = ap.parse_args()

    if not os.environ.get("CLOSE_API_KEY"):
        logger.error("CLOSE_API_KEY not set")
        return 1

    fields = close_get("custom_field/lead/")["data"]
    by_name = {f["name"]: f for f in fields}
    ind_id = by_name.get("Industry", {}).get("id")
    bl = by_name.get(FIELD_NAME)
    logger.info("Custom field %r already exists: %s", FIELD_NAME, bool(bl))

    logger.info("Loading leads from Close...")
    leads, skip = [], 0
    while True:
        res = close_get(f"lead/?_limit=100&_skip={skip}")
        leads.extend(res["data"])
        if not res.get("has_more"):
            break
        skip += 100
    logger.info("  %d leads", len(leads))

    rows = []
    for lead in leads:
        name = lead.get("display_name") or ""
        industry = lead.get(f"custom.{ind_id}") if ind_id else ""
        line, reason, competitor = decide(name, industry)
        rows.append({
            "lead_id": lead["id"],
            "name": name,
            "status": lead.get("status_label", ""),
            "industry": industry or "",
            "business_line": line,
            "vic_competitor": "YES" if competitor else "",
            "reason": reason,
        })

    if args.limit:
        rows = rows[:args.limit]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    counts = collections.Counter(r["business_line"] for r in rows)
    reasons = collections.Counter(r["reason"] for r in rows)
    comps = [r for r in rows if r["vic_competitor"]]

    logger.info("\n%s", "=" * 64)
    logger.info("BUSINESS LINE PLAN")
    logger.info("%s", "=" * 64)
    for k in FIELD_CHOICES:
        logger.info("  %-6s %5d", k, counts.get(k, 0))
    logger.info("\n  by reason:")
    for r, c in reasons.most_common():
        logger.info("    %-56s %4d", r[:56], c)
    logger.info("\n  VIC COMPETITORS (never send VIC outreach): %d", len(comps))
    for c in comps[:15]:
        logger.info("    - %s", c["name"][:58])

    both = [r for r in rows if r["business_line"] == "BOTH"]
    review = [r for r in both if "review" in r["reason"]]
    logger.info("\n  BOTH total: %d   of which need your eye: %d",
                len(both), len(review))
    logger.info("  sample BOTH (confident):")
    for r in [x for x in both if "review" not in x["reason"]][:8]:
        logger.info("    - %s", r["name"][:58])
    logger.info("  sample BOTH (assumed GC, review):")
    for r in review[:8]:
        logger.info("    - %s", r["name"][:58])

    logger.info("\n  review file: %s", out)

    if not args.apply:
        logger.info("\nDRY RUN - nothing written to Close.")
        return 0

    if not bl:
        logger.info("\nCreating custom field %r...", FIELD_NAME)
        bl = close_write("custom_field/lead/", {
            "name": FIELD_NAME,
            "type": "choices",
            "accepts_multiple_values": False,
            "choices": FIELD_CHOICES,
        })
        logger.info("  created: %s", bl["id"])

    key = f"custom.{bl['id']}"
    logger.info("\nWriting Business Line to %d leads...", len(rows))
    ok = fail = 0
    for i, r in enumerate(rows, 1):
        try:
            close_write(f"lead/{r['lead_id']}/", {key: r["business_line"]},
                        method="PUT")
            ok += 1
        except Exception as e:
            fail += 1
            logger.error("  FAILED %s: %s", r["name"][:40], e)
        if i % 100 == 0:
            logger.info("  %d/%d", i, len(rows))
        time.sleep(0.15)
    logger.info("\n  updated: %d   failed: %d", ok, fail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
