"""
Three corrections to Close email content, agreed 2026-08-24.

1. UNSUBSCRIBE LINK
   The org had enable_unsubscribe_link=False and require_unsubscribe_link=False,
   and all 26 templates had unsubscribe_link_id=None. US CAN-SPAM requires a
   working opt-out in commercial email. Turning both org flags on makes Close
   append the default unsubscribe link to every sequence send, which is far
   safer than editing each template by hand.

2. REMOVE THE DORAL TESTIMONIAL
   "One property manager in Doral told us their tenant complaints about
   cleanliness dropped by 40%..." is a specific, quantified client claim.
   Removed from Commercial | Step 2 at the owner's instruction.

   Deliberately NOT touched:
     - Education | Step 3 mentions Doral inside a market pricing table
       ($0.10-$0.22/sqft). That is a rate reference, not a client claim.
     - In-House | Step 2 says in-house cleaning runs 30-40% above payroll.
       That is an industry generalization, not a testimonial.

3. BRAND NAME
   24 of 26 templates said "Scrub Squads" (plural). The business is
   "Scrub Squad". Fixes subjects and bodies only; internal template names are
   left alone so existing muscle memory still works. The scrubsquads.com
   domain is unaffected - the pattern requires a space and a capital S.

USAGE
    py tools/close_fix_templates.py            # preview, writes nothing
    py tools/close_fix_templates.py --apply
"""
import argparse
import base64
import difflib
import html
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
if _env.exists():
    for _l in _env.read_text(encoding="utf-8").splitlines():
        _s = _l.strip()
        if _s and not _s.startswith("#") and "=" in _s:
            _k, _v = _s.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BASE = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(
    f"{os.environ.get('CLOSE_API_KEY', '')}:".encode()).decode()
ORG_ID = "orga_DdtThKJW1FoJTi7AMGjqY2zVYQnAMYvRSWx2FtIpvoR"

DORAL_SENTENCE = re.compile(
    r"\s*<div>\s*One property manager in Doral[^<]*</div>\s*(<div><br></div>)?",
    re.I)
DORAL_PLAIN = re.compile(r"One property manager in Doral[^.]*\.\s*", re.I)
PLURAL = re.compile(r"Scrub Squads\b")


def call(path, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE}/{path}", data=data, method=method,
        headers={"Authorization": AUTH, "Accept": "application/json",
                 "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{e.code} {method} {path}: {e.read().decode()[:300]}")
    raise RuntimeError("retries exhausted")


def detag(s):
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"</(p|div)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(s)).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Write the changes. Without this, preview only.")
    args = ap.parse_args()

    org = call(f"organization/{ORG_ID}/")
    logger.info("ORG UNSUBSCRIBE SETTINGS")
    logger.info("  enable_unsubscribe_link  = %s -> True", org.get("enable_unsubscribe_link"))
    logger.info("  require_unsubscribe_link = %s -> True", org.get("require_unsubscribe_link"))

    templates = call("email_template/")["data"]
    changes = []
    possessives = []

    for meta in templates:
        t = call(f"email_template/{meta['id']}/")
        name = t.get("name", "")
        subj = t.get("subject", "") or ""
        body = t.get("body", "") or ""
        new_subj, new_body = subj, body

        if name == "Commercial | Step 2 - Why Scrub Squads":
            new_body = DORAL_SENTENCE.sub("", new_body)
            if "Doral" in new_body:
                new_body = DORAL_PLAIN.sub("", new_body)

        if re.search(r"Scrub Squads'", new_body) or re.search(r"Scrub Squads'", new_subj):
            possessives.append(name)
        new_subj = PLURAL.sub("Scrub Squad", new_subj)
        new_body = PLURAL.sub("Scrub Squad", new_body)

        if new_subj != subj or new_body != body:
            changes.append({
                "id": t["id"], "name": name,
                "subject": new_subj, "body": new_body,
                "subj_changed": new_subj != subj,
                "body_before": body, "body_after": new_body,
            })

    logger.info("\nTEMPLATES TO UPDATE: %d of %d", len(changes), len(templates))
    if possessives:
        logger.info("  NOTE possessive 'Scrub Squads'' found in: %s", possessives)

    doral = next((c for c in changes if "Step 2 - Why" in c["name"]), None)
    if doral:
        logger.info("\n%s", "=" * 70)
        logger.info("DORAL REMOVAL — Commercial | Step 2, after edit")
        logger.info("%s", "=" * 70)
        for line in detag(doral["body_after"]).splitlines():
            logger.info("  %s", line)
        still = "Doral" in doral["body_after"]
        logger.info("\n  Doral still present: %s", still)

    logger.info("\n%s", "=" * 70)
    logger.info("BRAND RENAME — sample")
    logger.info("%s", "=" * 70)
    for c in changes[:6]:
        before = detag(c["body_before"])
        after = detag(c["body_after"])
        for b, a in zip(before.splitlines(), after.splitlines()):
            if b != a:
                logger.info("  %s", c["name"][:44])
                logger.info("    - %s", b.strip()[:88])
                logger.info("    + %s", a.strip()[:88])
                break

    if not args.apply:
        logger.info("\nPREVIEW ONLY — nothing written.")
        return 0

    logger.info("\nApplying...")
    call(f"organization/{ORG_ID}/", "PUT", {
        "enable_unsubscribe_link": True,
        "require_unsubscribe_link": True,
    })
    logger.info("  org unsubscribe settings: ON")

    ok = fail = 0
    for c in changes:
        try:
            call(f"email_template/{c['id']}/", "PUT",
                 {"subject": c["subject"], "body": c["body"]})
            ok += 1
        except Exception as e:
            fail += 1
            logger.error("  FAILED %s: %s", c["name"], e)
        time.sleep(0.2)
    logger.info("  templates updated: %d   failed: %d", ok, fail)

    check = call(f"organization/{ORG_ID}/")
    logger.info("\nVERIFY  enable=%s  require=%s",
                check.get("enable_unsubscribe_link"),
                check.get("require_unsubscribe_link"))
    left = sum(1 for m in call("email_template/")["data"]
               if PLURAL.search(json.dumps(call(f"email_template/{m['id']}/"))))
    logger.info("VERIFY  templates still containing the plural: %d", left)
    return 0


if __name__ == "__main__":
    sys.exit(main())
