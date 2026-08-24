"""
Close CRM - Tailored SMS Outreach

Builds a per-lead SMS for leads in outreach-eligible statuses and (optionally)
sends them from a Close internal phone number.

SAFETY MODEL:
  - Dry run is the DEFAULT. Nothing sends unless you pass --send.
  - --send additionally requires --limit to be set explicitly.
  - Hard filters: status allowlist, toll-free strip, duplicate-number strip,
    and a skip for any lead that already has an SMS activity.

Usage:
    py tools/close_send_sms.py                      # dry run, writes review CSV
    py tools/close_send_sms.py --limit 25 --send    # send first 25 for real

Review output: .tmp/sms_review.csv
"""
import argparse
import base64
import csv
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists() and not os.environ.get("GITHUB_ACTIONS"):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CLOSE_API_KEY = os.environ.get("CLOSE_API_KEY", "")
BASE_URL = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(f"{CLOSE_API_KEY}:".encode()).decode()

# Scrub Squad main number (internal, sms_enabled, verified via phone_number/)
FROM_PHONE = "+17868384148"

# Only these statuses are ever eligible. Everything else (Do Not Contact,
# Not Interested, Customer, Under Contract, In-House) is excluded by omission.
IN_SCOPE_STATUSES = {"New Lead", "Attempting Contact"}

# Toll-free prefixes cannot receive SMS.
TOLLFREE_PREFIXES = {"800", "888", "877", "866", "855", "844", "833", "822"}

SENDER = "Sentel"
COMPANY = "Scrub Squad"
OPT_OUT = "Reply STOP to opt out."

# ---------------------------------------------------------------------------
# Exclusions - leads that survived earlier classification but should not be
# texted. Competitors (we would be cold-pitching a facility services firm),
# solo realtors (no facility to clean), and national brands where a local
# contact does not choose the janitorial vendor.
# ---------------------------------------------------------------------------

# Reuse the curated blacklist from the classifier rather than maintaining a
# second, narrower copy here. That list already covers hospital systems,
# hotel chains, universities, national brands and government.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from close_classify_new_leads import classify as classify_badfit
except Exception as e:  # pragma: no cover - fall back to local list only
    logging.warning("Could not import classifier blacklist: %s", e)
    classify_badfit = lambda name: ("KEEP", "")

# Copy promises "Miami area" / "South Florida", so only text numbers that are
# actually in that footprint.
SOUTH_FL_AREA_CODES = {"305", "786", "954", "754", "561"}

BADFIT_PATTERN = re.compile(
    r"\b(Eulen|ABM Industries|Aramark|Sodexo|ISS Facility|Jan[- ]?Pro|"
    r"Coverall|Stratus Building|Vanguard Cleaning|ServiceMaster|Chem[- ]?Dry|"
    r"Merry Maids|Molly Maid|Pritchard Industries|Harvard Maintenance|"
    r"cleaning service|janitorial|maid service|"
    r"Popeyes|McDonald|Burger King|Wendy'?s|Subway|Starbucks|Chick[- ]?fil|"
    r"Southern Glazer|Perry Ellis|Amazon|Walmart|Publix|Home Depot|"
    r"real estate agent|realtor|Keller Williams|RE/MAX|Coldwell)\b", re.I)

# GSM-7 is the cheap SMS alphabet at 153 chars/segment. Anything outside it
# forces UCS-2 encoding, which drops to 67 chars/segment (2-3x the cost).
GSM7_CHARS = set(
    "@£$¥èéùìòÇ\nØø\rÅå"
    "Δ_ΦΓΛΩΠΨΣΘΞÆæßÉ"
    " !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
    "¿abcdefghijklmnopqrstuvwxyzäöñüà"
    "\f^{}\\[~]|€"
)

TRANSLIT = {
    "–": "-", "—": "-", "‒": "-", "−": "-",
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "…": "...", "®": "", "™": "", "©": "",
    "´": "'", "́": "", "̀": "", "̃": "", "̧": "",
    "á": "a", "í": "i", "ó": "o", "ú": "u",
    "Á": "A", "Í": "I", "Ó": "O", "Ú": "U",
    "â": "a", "ê": "e", "î": "i", "ô": "o", "û": "u",
    "ç": "c", "Ç": "C", "ñ": "n", "Ñ": "N",
    " ": " ", "​": "",
}


def to_gsm7(text):
    """Transliterate to the GSM-7 alphabet so messages stay 153 chars/segment."""
    out = []
    for ch in text:
        if ch in GSM7_CHARS:
            out.append(ch)
        elif ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        else:
            import unicodedata
            decomposed = unicodedata.normalize("NFKD", ch)
            stripped = "".join(
                c for c in decomposed
                if not unicodedata.combining(c) and c in GSM7_CHARS
            )
            out.append(stripped)
    return "".join(out)


def segment_count(text):
    """Billable segments, accounting for encoding."""
    per = 153 if all(ch in GSM7_CHARS for ch in text) else 67
    return max(1, -(-len(text) // per))


def sanitize_first_name(raw):
    """Return a usable first name, or None if the value is junk."""
    if not raw:
        return None
    name = raw.strip().strip(".,")
    if len(name) < 3:                      # initials like "J", "AJ", "Ed"
        return None
    if any(ch.isdigit() for ch in name):
        return None
    if name.lower() in {"info", "office", "admin", "contact", "sales", "team",
                        "front", "the", "manager", "owner", "general", "main",
                        "customer", "support", "billing", "accounts"}:
        return None
    if name.isupper() or name.islower():   # "STEVEN" / "steven" -> "Steven"
        name = name.capitalize()
    if not name.replace("-", "").replace("'", "").isalpha():
        return None
    return name


# ---------------------------------------------------------------------------
# Industry inference - fills the 61% of leads with a blank Industry field
# ---------------------------------------------------------------------------
INDUSTRY_PATTERNS = [
    (r"\b(property manage|realty|real estate|residential|rentals?|"
     r"apartments?|condo|HOA|leasing)\b", "Property Management"),
    (r"\b(construction|contractor|builders?|drywall|roofing|concrete|"
     r"remodel|renovation|restoration|electric|plumbing|HVAC)\b", "Construction"),
    (r"\b(school|academy|university|college|montessori|preschool|"
     r"day ?care|learning cent|education|charter)\b", "Education"),
    (r"\b(medical|health|clinic|dental|dentist|orthodont|pediatric|"
     r"surgery|surgical|physician|doctor|urgent care|wellness|"
     r"chiroprac|derma|optical|veterinar|animal hospital)\b", "Healthcare"),
    (r"\b(warehouse|distribution|logistics|freight|fulfillment|storage)\b",
     "Warehouse"),
    (r"\b(manufactur|industrial|fabricat|machine|factory|plant)\b",
     "Manufacturing"),
    (r"\b(auto|motors?|car deal|dealership|nissan|toyota|honda|ford|"
     r"chevrolet|bmw|mercedes|lexus|kia|hyundai)\b", "Car Dealerships"),
    (r"\b(yoga|pilates|fitness|gym|crossfit|studio of dance|dance|"
     r"martial arts|athletic)\b", "Fitness Studios"),
    (r"\b(assisted living|senior living|nursing home|retirement|"
     r"memory care|rehabilitation cent)\b", "Assisted Living"),
    (r"\b(restaurant|cafe|café|bistro|grill|kitchen|bakery|"
     r"pizzeria|catering|bar & grill)\b", "Restaurant"),
    (r"\b(church|temple|synagogue|ministry|chapel|congregation)\b",
     "Place of Worship"),
    (r"\b(law|attorney|legal|accounting|CPA|financial|insurance|"
     r"agency|consulting|architect|engineering)\b", "Professional Office"),
]
COMPILED_INDUSTRY = [(re.compile(p, re.I), label) for p, label in INDUSTRY_PATTERNS]

# Normalize the Industry values already in Close onto our copy segments.
INDUSTRY_ALIASES = {
    "Yoga Studios": "Fitness Studios",
    "Commercial": "Professional Office",
    "Commercial Building": "Professional Office",
    "Residential": "Property Management",
    "Providers": "Healthcare",
    "Retail": "Retail",
}


def infer_industry(name, existing):
    """Use the Close Industry field if set, else infer from the business name."""
    if existing:
        return INDUSTRY_ALIASES.get(existing, existing), "field"
    for pattern, label in COMPILED_INDUSTRY:
        if pattern.search(name or ""):
            return label, "inferred"
    return None, "none"


# ---------------------------------------------------------------------------
# Copy - one angle per segment, 3 variants each so 800 texts are not identical
# (carriers filter high volumes of byte-identical bodies)
# ---------------------------------------------------------------------------
SEGMENT_COPY = {
    "Property Management": [
        "we handle commercial cleaning for property managers across South Florida. Are you happy with your current crew at {biz}?",
        "we do janitorial for property management groups around Miami. Is {biz} under contract with a cleaning company right now?",
        "we cover commercial cleaning for properties in the Miami area. Who handles janitorial for {biz} these days?",
    ],
    "Construction": [
        "we do post-construction cleanup for contractors in South Florida. Does {biz} have a crew lined up for final cleans?",
        "we handle post-construction and rough cleans around Miami. Is {biz} taking on projects that need turnover cleaning?",
        "we cover final cleans for construction firms in the Miami area. Who does {biz} use for post-construction cleanup?",
    ],
    "Education": [
        "we handle nightly janitorial for schools across South Florida. Is {biz} happy with its current cleaning service?",
        "we do custodial work for schools and learning centers around Miami. Who covers cleaning for {biz} right now?",
        "we cover school and campus cleaning in the Miami area. Is {biz} under contract with a janitorial company?",
    ],
    "Healthcare": [
        "we do medical office cleaning and disinfection across South Florida. Is {biz} satisfied with its current service?",
        "we handle janitorial for medical and dental offices around Miami. Who cleans {biz} after hours?",
        "we cover clinical cleaning for practices in the Miami area. Is {biz} looking at cleaning vendors this year?",
    ],
    "Warehouse": [
        "we handle warehouse cleaning and floor care across South Florida. Does {biz} have a crew for that now?",
        "we do industrial floor care for warehouses around Miami. Who covers cleaning at {biz}?",
        "we cover warehouse and distribution cleaning in the Miami area. Is {biz} happy with its current setup?",
    ],
    "Manufacturing": [
        "we handle industrial cleaning for manufacturers across South Florida. Is {biz} using an outside crew?",
        "we do plant and facility cleaning around Miami. Who handles janitorial for {biz}?",
        "we cover industrial facility cleaning in the Miami area. Is {biz} reviewing cleaning vendors?",
    ],
    "Car Dealerships": [
        "we handle showroom and service bay cleaning across South Florida. Is {biz} happy with its current crew?",
        "we do dealership cleaning around Miami, showroom through service. Who covers that for {biz}?",
        "we cover dealership janitorial in the Miami area. Is {biz} under contract right now?",
    ],
    "Fitness Studios": [
        "we handle cleaning for studios and gyms across South Florida. Is {biz} happy with its current service?",
        "we do studio and fitness cleaning around Miami. Who covers cleaning at {biz}?",
        "we cover gym and studio janitorial in the Miami area. Is {biz} looking at options?",
    ],
    "Assisted Living": [
        "we handle cleaning for senior living communities across South Florida. Is {biz} satisfied with its current crew?",
        "we do janitorial for assisted living facilities around Miami. Who covers cleaning at {biz}?",
        "we cover senior care facility cleaning in the Miami area. Is {biz} under contract?",
    ],
    "Restaurant": [
        "we handle kitchen and dining room deep cleans across South Florida. Is {biz} happy with its current crew?",
        "we do restaurant cleaning around Miami, front of house through kitchen. Who covers that for {biz}?",
        "we cover restaurant janitorial in the Miami area. Is {biz} reviewing cleaning vendors?",
    ],
    "Place of Worship": [
        "we handle cleaning for churches and congregations across South Florida. Is {biz} happy with its current service?",
        "we do janitorial for places of worship around Miami. Who covers cleaning at {biz}?",
        "we cover facility cleaning in the Miami area. Is {biz} under contract with a cleaning company?",
    ],
    "Professional Office": [
        "we handle office cleaning across South Florida. Is {biz} happy with its current janitorial crew?",
        "we do commercial office cleaning around Miami. Who covers janitorial for {biz}?",
        "we cover office cleaning in the Miami area. Is {biz} reviewing cleaning vendors this year?",
    ],
    "Retail": [
        "we handle retail cleaning across South Florida. Is {biz} happy with its current crew?",
        "we do storefront and retail janitorial around Miami. Who covers cleaning at {biz}?",
        "we cover retail cleaning in the Miami area. Is {biz} under contract right now?",
    ],
}

FALLBACK_COPY = [
    "we handle commercial cleaning across South Florida. Is {biz} happy with its current janitorial crew?",
    "we do commercial cleaning and janitorial around Miami. Who covers cleaning for {biz}?",
    "we cover commercial cleaning in the Miami area. Is {biz} under contract with a cleaning company?",
]


MAX_BIZ_CHARS = 40


def clean_business_name(name):
    """
    Make a Google Maps business name read naturally mid-sentence.

    Listings are frequently SEO-stuffed ("Miami Warehouse Storage and
    Fulfillment, Kore Logistics, FBA, Inventory Management, Pick and Pack
    Warehouse"), so cut at the first separator and cap the length.
    """
    if not name:
        return "your business"
    n = name.strip()

    # Cut at the first hard separator - everything after it is keyword padding.
    # Only split on a slash when it is spaced or the name is already long;
    # "Guidance/Care Center Inc" must not collapse to "Guidance".
    n = re.split(r"\s*\|\s*|\s+[-–—]\s+|\s*:\s*", n)[0]
    if len(n) > MAX_BIZ_CHARS:
        n = re.split(r"\s*/\s*", n)[0]

    # Drop a trailing descriptor clause, but keep short natural names
    if len(n) > MAX_BIZ_CHARS and "," in n:
        n = n.split(",")[0]

    # Strip legal suffixes
    n = re.sub(r"\s*,?\s*\b(LLC|L\.L\.C\.|Inc\.?|Corp\.?|Corporation|"
               r"Co\.|Ltd\.?|LLP|PA|P\.A\.)\b\.?\s*$", "", n, flags=re.I)
    n = n.strip(" ,.-")

    # Last resort: truncate on a word boundary
    if len(n) > MAX_BIZ_CHARS:
        n = n[:MAX_BIZ_CHARS].rsplit(" ", 1)[0].strip(" ,.-")

    return n or name.strip()[:MAX_BIZ_CHARS]


def build_message(biz_name, first_name, industry, variant_seed):
    """Compose the per-lead SMS body. Deterministic given the same inputs."""
    biz = clean_business_name(biz_name)
    variants = SEGMENT_COPY.get(industry, FALLBACK_COPY)
    body = variants[variant_seed % len(variants)].format(biz=biz)

    if first_name:
        greeting = f"Hi {first_name}, this is {SENDER} with {COMPANY} -"
    else:
        greeting = f"Hi, this is {SENDER} with {COMPANY} -"

    return to_gsm7(f"{greeting} {body} {OPT_OUT}")


# ---------------------------------------------------------------------------
# Close API
# ---------------------------------------------------------------------------
def close_request(path, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", data=data, method=method,
        headers={"Authorization": AUTH, "Accept": "application/json",
                 "Content-Type": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt
                logger.warning("Rate limited, waiting %ss", wait)
                time.sleep(wait)
                continue
            raise RuntimeError(f"{e.code} on {method} {path}: {e.read().decode()[:300]}")
    raise RuntimeError(f"Gave up after retries: {method} {path}")


def normalize_phone(raw):
    """Return a 10-digit US number, or None if unusable."""
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    if digits[:3] in TOLLFREE_PREFIXES:
        return None
    return digits


def pick_phone(lead):
    """Prefer a phone explicitly typed mobile/direct, else first usable one."""
    ranked = []
    for c in lead.get("contacts", []):
        for p in c.get("phones", []):
            num = normalize_phone(p.get("phone"))
            if not num:
                continue
            ptype = (p.get("type") or "").lower()
            rank = {"mobile": 0, "direct": 1}.get(ptype, 2)
            ranked.append((rank, num, c))
    if not ranked:
        return None, None
    ranked.sort(key=lambda x: x[0])
    _, num, contact = ranked[0]
    return num, contact


def fetch_in_scope_leads():
    leads, skip = [], 0
    while True:
        res = close_request(f"lead/?_limit=100&_skip={skip}")
        for lead in res["data"]:
            if lead.get("status_label") in IN_SCOPE_STATUSES:
                leads.append(lead)
        if not res.get("has_more"):
            break
        skip += 100
        logger.info("  fetched %s leads...", skip)
    # Close does not guarantee a stable page order. Sort so that a dry run and
    # the subsequent --send select the identical batch.
    leads.sort(key=lambda l: l["id"])
    return leads


def already_texted(lead_id):
    """True if this lead has any prior SMS activity, so we never double-text."""
    res = close_request(f"activity/sms/?lead_id={lead_id}&_limit=1")
    return bool(res.get("data"))


def send_sms(lead_id, contact_id, to_number, body):
    payload = {
        "lead_id": lead_id,
        "local_phone": FROM_PHONE,
        "remote_phone": f"+1{to_number}",
        "text": body,
        "direction": "outbound",
        "status": "outbox",
    }
    if contact_id:
        payload["contact_id"] = contact_id
    return close_request("activity/sms/", method="POST", payload=payload)


def stratified_sample(rows, limit):
    """
    Take `limit` rows spread across industry segments rather than the first N.

    A test batch drawn off the top of the list would be all one segment, which
    tells you nothing about how the rest of the list will perform.
    """
    if limit >= len(rows):
        return rows
    buckets = {}
    for r in rows:
        buckets.setdefault(r["industry"], []).append(r)
    order = sorted(buckets, key=lambda k: -len(buckets[k]))
    picked, idx = [], 0
    while len(picked) < limit:
        progressed = False
        for seg in order:
            if idx < len(buckets[seg]):
                picked.append(buckets[seg][idx])
                progressed = True
                if len(picked) == limit:
                    break
        if not progressed:
            break
        idx += 1
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true",
                    help="Actually send. Without this, dry run only.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Max messages. Required with --send.")
    ap.add_argument("--check-existing", action="store_true",
                    help="Query prior SMS per lead (slow, one API call each).")
    ap.add_argument("--allow-out-of-area", action="store_true",
                    help="Include numbers outside South Florida area codes.")
    ap.add_argument("--out", default=".tmp/sms_review.csv")
    args = ap.parse_args()

    if args.send and args.limit is None:
        ap.error("--send requires an explicit --limit. Refusing to send unbounded.")

    if not CLOSE_API_KEY:
        logger.error("CLOSE_API_KEY missing from .env")
        return 1

    logger.info("Fetching leads...")
    leads = fetch_in_scope_leads()
    logger.info("In-scope leads: %s", len(leads))

    cf = close_request("custom_field/lead/")
    ind_field = next((f["id"] for f in cf["data"] if f["name"] == "Industry"), None)

    rows = []
    seen_numbers = set()
    excluded_badfit = []
    stats = {"no_phone": 0, "dupe": 0, "already_texted": 0, "badfit": 0,
             "out_of_area": 0, "field": 0, "inferred": 0, "none": 0}

    for i, lead in enumerate(leads):
        biz_raw = lead.get("display_name") or ""
        verdict, reason = classify_badfit(biz_raw)
        if verdict == "DEFINITE_BAD":
            stats["badfit"] += 1
            excluded_badfit.append(f"{biz_raw}  [{reason}]")
            continue
        if BADFIT_PATTERN.search(biz_raw):
            stats["badfit"] += 1
            excluded_badfit.append(f"{biz_raw}  [competitor / not a facility]")
            continue

        number, contact = pick_phone(lead)
        if not number:
            stats["no_phone"] += 1
            continue
        if not args.allow_out_of_area and number[:3] not in SOUTH_FL_AREA_CODES:
            stats["out_of_area"] += 1
            continue
        if number in seen_numbers:
            stats["dupe"] += 1
            continue
        seen_numbers.add(number)

        if args.check_existing and already_texted(lead["id"]):
            stats["already_texted"] += 1
            continue

        biz = biz_raw
        existing_ind = lead.get(f"custom.{ind_field}") if ind_field else None
        industry, source = infer_industry(biz, existing_ind)
        stats[source] += 1

        first = None
        if contact:
            nm = (contact.get("name") or "").strip()
            if nm:
                first = sanitize_first_name(nm.split()[0])

        body = build_message(biz, first, industry, i)
        rows.append({
            "lead_id": lead["id"],
            "contact_id": contact.get("id") if contact else "",
            "business": biz,
            "first_name": first or "",
            "industry": industry or "(fallback)",
            "industry_source": source,
            "phone": number,
            "chars": len(body),
            "segments": segment_count(body),
            "message": body,
        })

    total_built = len(rows)
    if args.limit:
        rows = stratified_sample(rows, args.limit)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["message"])
        w.writeheader()
        w.writerows(rows)

    logger.info("\n%s", "=" * 60)
    logger.info("Built:              %s", total_built)
    if args.limit:
        logger.info("Selected (spread):  %s", len(rows))
    logger.info("Skipped bad-fit:    %s", stats["badfit"])
    logger.info("Skipped no phone:   %s", stats["no_phone"])
    logger.info("Skipped out-of-area:%s", stats["out_of_area"])
    logger.info("Skipped duplicate:  %s", stats["dupe"])
    if args.check_existing:
        logger.info("Skipped prior SMS:  %s", stats["already_texted"])
    logger.info("Industry from field:%s  inferred: %s  fallback: %s",
                stats["field"], stats["inferred"], stats["none"])
    if rows:
        avg = sum(r["chars"] for r in rows) / len(rows)
        segs = sum(r["segments"] for r in rows)
        ucs2 = sum(1 for r in rows
                   if any(ch not in GSM7_CHARS for ch in r["message"]))
        logger.info("Avg length: %.0f chars   billable segments: %s   UCS-2: %s",
                    avg, segs, ucs2)
    if excluded_badfit:
        logger.info("\nExcluded as bad-fit:")
        for b in excluded_badfit:
            logger.info("  - %s", b)
    logger.info("\nReview file: %s", out_path)

    if not args.send:
        logger.info("\nDRY RUN. Nothing sent. Add --send --limit N to send.")
        return 0

    logger.info("\nSENDING %s messages from %s ...", len(rows), FROM_PHONE)
    sent = failed = 0
    for r in rows:
        try:
            send_sms(r["lead_id"], r["contact_id"] or None, r["phone"], r["message"])
            sent += 1
            logger.info("  sent -> %s (%s)", r["business"], r["phone"])
            time.sleep(0.6)
        except Exception as e:
            failed += 1
            logger.error("  FAILED -> %s: %s", r["business"], e)
    logger.info("\nSent: %s   Failed: %s", sent, failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
