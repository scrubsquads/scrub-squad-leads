"""
Close CRM — Bounce Recovery & Opt-Out Suppression Handler

Runs alongside the existing reply-monitor cron. Finds two categories of
signal Close does NOT act on by itself:

  1. HARD BOUNCES — inbound "Delivery Status Notification (Failure)"
     messages (3 body formats handled: Close's own mailer-daemon relay,
     Gmail's "wasn't delivered to", and a generic "message... has been
     blocked" format). Nothing stops the underlying sequence from
     continuing to try that dead address on its next step.

     RECOVERY LADDER for a bounce (tries each in order, stops at first
     success — a bounced email is a bad ADDRESS, not necessarily a dead
     LEAD):
       a. ALT EMAIL ALREADY ON FILE — if the bounced contact has another,
          non-bounced email address in Close, just mark the bad one
          is_unsubscribed=true (Close's own per-address opt-out flag) and
          leave everything else alone. Free, no new lookups needed.
       b. WEBSITE SCRAPE — if the lead has a website on file, crawl it
          (same approach as tools/scrape_site_emails.py) for a plausible
          business email (info@, contact@, or a same-domain/free-provider
          address). If found, mark the old one is_unsubscribed and ADD
          the new one to the contact. Free.
       c. SMS FALLBACK — if no alt/scraped email exists but the contact
          has a usable South Florida phone number, kill only the EMAIL
          sequence subscriptions (mark the bad email unsubscribed) and
          leave any SMS subscription running — the lead stays reachable,
          just not by email. Free (uses phone already on file).
       d. FULL SUPPRESSION — only if a, b, and c all fail: delete every
          sequence subscription across every channel and mark the lead
          Do Not Contact with reason "Bounced Email". This is the
          previous (pre-recovery) behavior, now the last resort.

  2. STOP / OPT-OUT REPLIES — inbound SMS containing STOP, UNSUBSCRIBE,
     OPT OUT, REMOVE ME, etc. NO recovery ladder here by design — a
     person explicitly asking to stop being contacted gets fully
     suppressed on every channel, no exceptions, no re-routing to email.
     Close does not auto-detect these on manually-built sequences, so
     without this a STOP reply either gets an autonomous "routine" reply
     from the poll-reply cron, or silently keeps receiving sends on every
     OTHER channel (STOP on SMS does nothing to a parallel email
     sequence, and vice versa).

State tracked in .tmp/suppression_state.json (activity_id already
processed -> keeps re-runs idempotent).

USAGE
    python close_suppress_bounces_and_stops.py                # dry run
    python close_suppress_bounces_and_stops.py --apply
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for _l in _env.read_text(encoding="utf-8").splitlines():
        _s = _l.strip()
        if _s and not _s.startswith("#") and "=" in _s:
            _k, _v = _s.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apollo import extract_domain  # noqa: E402
from close_classify_new_leads import classify as classify_badfit  # noqa: E402

API_KEY = os.environ.get("CLOSE_API_KEY", "")
BASE_URL = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(f"{API_KEY}:".encode()).decode()

DQ_FIELD = "custom.cf_MlPTMe5OPR2ntV4iWvFytphf73cneOqvTIBdW2OXTp1"
DNC_STATUS_ID = "stat_PJQQKM8i2R39InBZAICdaMCvGcXT88HaDQiBmBFKpPT"

STATE_PATH = Path(__file__).resolve().parent.parent / ".tmp" / "suppression_state.json"

STOP_PATTERN = re.compile(
    r"^\s*(stop|unsubscribe|opt\s*out|remove\s*me|cancel|quit|end)\b",
    re.I,
)

BOUNCE_EMAIL_PATTERN = re.compile(
    r"failed permanently:\s*(?:<br>\s*)?([\w.\-+]+@[\w.\-]+)", re.I
)
BOUNCE_ALT_PATTERN = re.compile(
    r"Recipient address rejected.{0,80}?([\w.\-+]+@[\w.\-]+)", re.I
)
BOUNCE_GOOGLE_PATTERN = re.compile(
    r"wasn't delivered to.{0,60}?([\w.\-+]+@[\w.\-]+)", re.I
)
BOUNCE_BLOCKED_PATTERN = re.compile(
    r"message to.{0,60}?([\w.\-+]+@[\w.\-]+).{0,20}has been blocked", re.I
)

# --- website email scrape (trimmed copy of scrape_site_emails.py logic) ---
CONTACT_PATHS = ["", "/contact", "/contact-us", "/contactus", "/about", "/about-us"]
SITE_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
FREE_PROVIDERS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "live.com", "msn.com", "comcast.net", "bellsouth.net",
    "att.net", "verizon.net", "me.com", "mac.com", "protonmail.com",
}
JUNK_DOMAINS = {
    "sentry.io", "wixpress.com", "wix.com", "squarespace.com", "godaddy.com",
    "example.com", "domain.com", "email.com", "test.com", "w3.org",
    "schema.org", "cloudflare.com", "shopify.com", "wordpress.com",
}
JUNK_LOCAL_PARTS = {
    "email", "your", "name", "someone", "user", "example", "test", "sample",
    "no-reply", "noreply", "donotreply", "sentry",
}
ROLE_PRIORITY = ["info", "contact", "office", "admin", "hello", "sales"]
SOUTH_FL_AREA_CODES = {"305", "786", "954", "754", "561"}
TOLLFREE_PREFIXES = {"800", "888", "877", "866", "855", "844", "833", "822"}

# Competitor / obviously-not-a-fit patterns (reused from close_send_sms.py's
# blacklist) — a bounced email must NOT trigger recovery for these; a dead
# address on a competitor or a personal employee's inbox at a national brand
# is not a lead worth reviving, it just goes to full suppression like before.
COMPETITOR_OR_BADFIT_PATTERN = re.compile(
    r"\b(Eulen|ABM Industries|Aramark|Sodexo|ISS Facility|Jan[- ]?Pro|"
    r"Coverall|Stratus Building|Vanguard Cleaning|ServiceMaster|Chem[- ]?Dry|"
    r"Merry Maids|Molly Maid|Pritchard Industries|Harvard Maintenance|"
    r"cleaning service|janitorial|maid service|"
    r"Popeyes|McDonald|Burger King|Wendy'?s|Subway|Starbucks|Chick[- ]?fil|"
    r"Southern Glazer|Perry Ellis|Amazon|Walmart|Publix|Home Depot|"
    r"real estate agent|realtor|Keller Williams|RE/MAX|Coldwell|"
    r"American Express|Visa|Mastercard|Discover Card|Chase|Wells Fargo|"
    r"Bank of America|Citibank|Citigroup)\b", re.I)


def is_recovery_ineligible(lead_name):
    """True if this lead should never get the recovery ladder — it goes
    straight to full suppression regardless of bounce/recovery signals.
    Covers: known competitors (cleaning/janitorial companies), and
    obviously-not-a-fit national brands the name-based blacklist in
    close_classify_new_leads doesn't already catch by pattern."""
    if not lead_name:
        return False, None
    m = COMPETITOR_OR_BADFIT_PATTERN.search(lead_name)
    if m:
        return True, f"competitor/national-brand pattern: '{m.group(0)}'"
    verdict, reason = classify_badfit(lead_name)
    if verdict == "DEFINITE_BAD":
        return True, reason
    return False, None


def close_call(path, method="GET", data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", data=body, method=method,
        headers={"Authorization": AUTH, "Accept": "application/json", "Content-Type": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as r:
                if r.status == 204:
                    return {}
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{e.code} {method} {path}: {e.read().decode()[:300]}")
    raise RuntimeError("retries exhausted")


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"processed_activity_ids": [], "suppressed_leads": {}, "recovered_leads": {}}


def save_state(state):
    state.setdefault("recovered_leads", {})
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def find_bounce_email(activity):
    """Extract the dead recipient address from a bounce notification body."""
    blocks = activity.get("body_html_quoted", []) or []
    text = " ".join(b.get("html", "") for b in blocks)
    text += (activity.get("body_html") or "") + (activity.get("body_text") or "")
    m = (BOUNCE_EMAIL_PATTERN.search(text) or BOUNCE_ALT_PATTERN.search(text)
         or BOUNCE_GOOGLE_PATTERN.search(text) or BOUNCE_BLOCKED_PATTERN.search(text))
    return m.group(1) if m else None


def find_lead_contact_by_email(email):
    """Search Close for the lead/contact owning this email address."""
    q = f'email:"{email}"'
    res = close_call(f"lead/?query={urllib.parse.quote(q)}&_limit=5")
    for lead in res.get("data", []):
        for c in lead.get("contacts", []):
            for e in (c.get("emails") or []):
                if e.get("email", "").lower() == email.lower():
                    return lead["id"], c["id"], lead.get("display_name")
    return None, None, None


def clean_site_email(addr, site_domain):
    addr = addr.strip().strip(".,;:<>()[]\"'").lower()
    if "@" not in addr:
        return None
    local, _, dom = addr.rpartition("@")
    if not local or not dom or "." not in dom:
        return None
    if local in JUNK_LOCAL_PARTS or local.isdigit():
        return None
    if dom in JUNK_DOMAINS or any(dom.endswith("." + j) for j in JUNK_DOMAINS):
        return None
    if dom == site_domain or dom.endswith("." + site_domain) or dom in FREE_PROVIDERS:
        return addr
    return None


def scrape_site_for_email(website, exclude_email):
    """Best-effort crawl of a lead's own website for a plausible business
    email that isn't the one that just bounced. Returns None on any failure
    — this must never raise and block the recovery ladder."""
    try:
        import requests
    except ImportError:
        return None
    site_domain = extract_domain(website) or ""
    if not site_domain:
        return None
    base = website if website.startswith("http") else "https://" + website
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ScrubSquadLeadBot/1.0)"})
    found = set()
    for path in CONTACT_PATHS:
        try:
            url = urljoin(base, path) if path else base
            r = session.get(url, timeout=8, allow_redirects=True)
            if r.status_code != 200 or "text/html" not in r.headers.get("Content-Type", ""):
                continue
            html = r.text[:400_000]
            for m in SITE_EMAIL_RE.findall(html):
                c = clean_site_email(m, site_domain)
                if c and c.lower() != exclude_email.lower():
                    found.add(c)
        except Exception:
            continue
        if found:
            break
    if not found:
        return None
    ranked = sorted(found, key=lambda e: (0 if e.rpartition("@")[2] == site_domain else 1,
                                          ROLE_PRIORITY.index(e.split("@")[0]) if e.split("@")[0] in ROLE_PRIORITY else 99))
    return ranked[0]


def usable_sms_phone(contact):
    """Return a normalized 10-digit South Florida phone if this contact has
    one worth falling back to for SMS, else None."""
    for p in (contact.get("phones") or []):
        digits = "".join(ch for ch in str(p.get("phone") or "") if ch.isdigit())
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            continue
        if digits[:3] in TOLLFREE_PREFIXES:
            continue
        if digits[:3] in SOUTH_FL_AREA_CODES:
            return digits
    return None


def mark_email_unsubscribed(contact_id, bad_email):
    contact = close_call(f"contact/{contact_id}/")
    emails = contact.get("emails") or []
    changed = False
    for e in emails:
        if e.get("email", "").lower() == bad_email.lower():
            e["is_unsubscribed"] = True
            changed = True
    if changed:
        close_call(f"contact/{contact_id}/", "PUT", {"emails": emails})
    return changed


def add_email_to_contact(contact_id, new_email):
    contact = close_call(f"contact/{contact_id}/")
    emails = contact.get("emails") or []
    if any(e.get("email", "").lower() == new_email.lower() for e in emails):
        return
    emails.append({"email": new_email, "type": "office"})
    close_call(f"contact/{contact_id}/", "PUT", {"emails": emails})


def kill_email_subscriptions_only(lead_id, all_subs_by_contact):
    """Delete only EMAIL-channel sequence subscriptions for this lead's
    contacts (used for the SMS-fallback recovery path). Sequences with
    'SMS' in the name are left untouched. Best-effort name match since
    sequence_subscription doesn't carry a channel field directly."""
    lead = close_call(f"lead/{lead_id}/")
    contact_ids = {c["id"] for c in lead.get("contacts", [])}
    killed = []
    for cid in contact_ids:
        for seq_name, sub_id, status in all_subs_by_contact.get(cid, []):
            if "SMS" in seq_name.upper():
                continue
            if status in ("active", "paused", "error"):
                close_call(f"sequence_subscription/{sub_id}/", "DELETE")
                killed.append((seq_name, sub_id))
                time.sleep(0.15)
    return killed


def suppress_lead(lead_id, reason_tag, dry_run=True, all_subs_by_contact=None):
    """Delete every sequence_subscription for every contact on this lead,
    across ALL sequences, then mark Do Not Contact + tag the reason.

    all_subs_by_contact: optional pre-built {contact_id: [(seq_name, sub_id, status), ...]}
    index so repeated calls in one run don't each re-scan every sequence
    from scratch (O(sequences) once total instead of O(leads * sequences))."""
    lead = close_call(f"lead/{lead_id}/")
    contact_ids = {c["id"] for c in lead.get("contacts", [])}
    killed = []
    if not dry_run:
        if all_subs_by_contact is not None:
            for cid in contact_ids:
                for seq_name, sub_id, status in all_subs_by_contact.get(cid, []):
                    if status in ("active", "paused", "error"):
                        close_call(f"sequence_subscription/{sub_id}/", "DELETE")
                        killed.append((seq_name, sub_id))
                        time.sleep(0.15)
        else:
            sequences = close_call("sequence/?_limit=200")["data"]
            for seq in sequences:
                skip = 0
                while True:
                    res = close_call(f"sequence_subscription/?sequence_id={seq['id']}&_limit=200&_skip={skip}")
                    subs = res.get("data", [])
                    for s in subs:
                        if s.get("contact_id") in contact_ids and s.get("status") in ("active", "paused", "error"):
                            close_call(f"sequence_subscription/{s['id']}/", "DELETE")
                            killed.append((seq["name"], s["id"]))
                            time.sleep(0.15)
                    if not res.get("has_more"):
                        break
                    skip += 200

        close_call(f"lead/{lead_id}/", "PUT", {DQ_FIELD: reason_tag, "status_id": DNC_STATUS_ID})
    return killed


def build_subs_index():
    """One pass over every sequence, indexed by contact_id, so N leads to
    process in one run costs O(sequences) total instead of O(leads*sequences)."""
    index = {}
    sequences = close_call("sequence/?_limit=200")["data"]
    for seq in sequences:
        skip = 0
        while True:
            res = close_call(f"sequence_subscription/?sequence_id={seq['id']}&_limit=200&_skip={skip}")
            for s in res.get("data", []):
                cid = s.get("contact_id")
                if cid:
                    index.setdefault(cid, []).append((seq["name"], s["id"], s["status"]))
            if not res.get("has_more"):
                break
            skip += 200
    return index


def attempt_bounce_recovery(lead_id, contact_id, bad_email, dry_run, subs_index):
    """Try, in order: alt email on file -> website scrape -> SMS fallback.
    Returns (recovered: bool, method: str, detail: str).

    A competitor or obviously-not-a-fit lead (national brand, etc.) never
    enters the ladder at all — it's excluded up front and the caller falls
    straight through to full suppression, same as if no recovery path
    existed."""
    lead = close_call(f"lead/{lead_id}/")

    ineligible, reason = is_recovery_ineligible(lead.get("display_name"))
    if ineligible:
        return False, None, f"recovery skipped: {reason}"

    contact = next((c for c in lead.get("contacts", []) if c["id"] == contact_id), None)
    if not contact:
        return False, None, None

    other_emails = [e["email"] for e in (contact.get("emails") or [])
                    if e.get("email", "").lower() != bad_email.lower() and not e.get("is_unsubscribed")]

    # (a) Alt email already on file
    if other_emails:
        if not dry_run:
            mark_email_unsubscribed(contact_id, bad_email)
        return True, "alt_email_on_file", other_emails[0]

    # (b) Website scrape
    website = lead.get("url") or ""
    if website:
        found = scrape_site_for_email(website, bad_email)
        if found:
            if not dry_run:
                mark_email_unsubscribed(contact_id, bad_email)
                add_email_to_contact(contact_id, found)
            return True, "website_scrape", found

    # (c) SMS fallback
    phone = usable_sms_phone(contact)
    if phone:
        if not dry_run:
            mark_email_unsubscribed(contact_id, bad_email)
            kill_email_subscriptions_only(lead_id, subs_index or {})
            close_call(f"lead/{lead_id}/", "PUT", {DQ_FIELD: "Bounced Email"})
        return True, "sms_fallback", phone

    return False, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually act. Without this, dry run only.")
    args = ap.parse_args()

    if not API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        return 1

    state = load_state()
    processed = set(state["processed_activity_ids"])
    to_process_bounces = []  # (lead_id, contact_id, name, activity_id, bad_email)
    to_suppress_stops = []   # (lead_id, name, activity_id, detail) — no recovery, ever

    # --- 1. Bounces ---
    print("Scanning for bounce notifications...")
    skip = 0
    bounce_count = 0
    while skip < 2000:
        res = close_call(f"activity/email/?_limit=100&_skip={skip}")
        data = res.get("data", [])
        for a in data:
            if a["id"] in processed:
                continue
            if "Delivery Status Notification" not in (a.get("subject") or ""):
                continue
            bounce_count += 1
            email = find_bounce_email(a)
            if not email:
                print(f"  WARN: could not parse recipient from bounce {a['id']}")
                processed.add(a["id"])
                continue
            lead_id, contact_id, name = find_lead_contact_by_email(email)
            if not lead_id:
                print(f"  bounce for {email} — no matching lead in Close, skipping")
                processed.add(a["id"])
                continue
            to_process_bounces.append((lead_id, contact_id, name or email, a["id"], email))
        if not data or not res.get("has_more"):
            break
        skip += 100
    print(f"  bounce notifications seen: {bounce_count}, new to process: {len(to_process_bounces)}")

    # --- 2. STOP replies — always full suppression, no recovery attempted ---
    print("Scanning for STOP/opt-out replies...")
    skip = 0
    stop_count = 0
    while skip < 2000:
        res = close_call(f"activity/sms/?_limit=100&_skip={skip}")
        data = res.get("data", [])
        for a in data:
            if a["id"] in processed:
                continue
            if a.get("direction") not in ("inbound", "incoming"):
                continue
            text = (a.get("text") or "").strip()
            if not STOP_PATTERN.match(text):
                continue
            stop_count += 1
            lead_id = a.get("lead_id")
            if not lead_id:
                processed.add(a["id"])
                continue
            lead = close_call(f"lead/{lead_id}/")
            to_suppress_stops.append((lead_id, lead.get("display_name"), a["id"], text[:40]))
        if not data or not res.get("has_more"):
            break
        skip += 100
    print(f"  STOP-pattern inbound SMS seen: {stop_count}, new to process: {len(to_suppress_stops)}")

    if not to_process_bounces and not to_suppress_stops:
        print("\nNothing new to suppress.")
        if not args.apply:
            print("DRY RUN — no state changes.")
        return 0

    print(f"\n{'=' * 60}")
    print(f"{'APPLYING' if args.apply else 'PREVIEW'}: {len(to_process_bounces)} bounce(s), "
          f"{len(to_suppress_stops)} stop(s)")
    print(f"{'=' * 60}")

    already_suppressed = set(state["suppressed_leads"].keys())
    already_recovered = set(state.get("recovered_leads", {}).keys())
    subs_index = build_subs_index() if args.apply else None

    # Bounces: try recovery ladder first
    for lead_id, contact_id, name, activity_id, bad_email in to_process_bounces:
        if lead_id in already_suppressed or lead_id in already_recovered:
            print(f"  SKIP (already handled earlier or duplicate in this run): {name} [{bad_email}]")
            processed.add(activity_id)
            continue
        recovered, method, detail = attempt_bounce_recovery(
            lead_id, contact_id, bad_email, dry_run=not args.apply, all_subs_by_contact=subs_index)
        if recovered:
            already_recovered.add(lead_id)
            print(f"  RECOVERED: {name:35} via {method:18} -> {detail}")
            if args.apply:
                state.setdefault("recovered_leads", {})[lead_id] = {
                    "name": name, "bad_email": bad_email, "method": method, "detail": detail,
                }
        else:
            already_suppressed.add(lead_id)
            print(f"  {name:40} reason=Bounced Email (no recovery option) detail={bad_email}")
            if args.apply:
                killed = suppress_lead(lead_id, "Bounced Email", dry_run=False, all_subs_by_contact=subs_index)
                for seq_name, sub_id in killed:
                    print(f"      unsubscribed from: {seq_name}")
                state["suppressed_leads"][lead_id] = {
                    "name": name, "reason": "Bounced Email", "detail": bad_email,
                    "subscriptions_killed": len(killed),
                }
        processed.add(activity_id)

    # STOP replies: always full suppression, no recovery
    for lead_id, name, activity_id, detail in to_suppress_stops:
        if lead_id in already_suppressed:
            print(f"  SKIP (already suppressed earlier or duplicate in this run): {name} [{detail}]")
            processed.add(activity_id)
            continue
        already_suppressed.add(lead_id)
        print(f"  {name:40} reason=Opted Out             detail={detail}")
        if args.apply:
            killed = suppress_lead(lead_id, "Opted Out", dry_run=False, all_subs_by_contact=subs_index)
            for seq_name, sub_id in killed:
                print(f"      unsubscribed from: {seq_name}")
            state["suppressed_leads"][lead_id] = {
                "name": name, "reason": "Opted Out", "detail": detail,
                "subscriptions_killed": len(killed),
            }
        processed.add(activity_id)

    if args.apply:
        state["processed_activity_ids"] = list(processed)
        save_state(state)
        print(f"\nDONE. Suppressed all-time: {len(state['suppressed_leads'])}  "
              f"Recovered all-time: {len(state.get('recovered_leads', {}))}")
    else:
        print("\nDRY RUN — nobody actually changed, no state saved.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
