"""
Close CRM — Sync New Leads from Google Sheets
Reads Leads + Contacts from Google Sheets, creates them in Close CRM,
and subscribes to the appropriate email sequence.

Deduplicates using place_id custom field in Close.
Run daily after enrichment (Job 3 in GitHub Actions pipeline).
"""
import argparse
import json
import time
import urllib.request
import urllib.error
import urllib.parse
import base64
import os
import sys
import logging
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Load .env if running locally (GitHub Actions injects secrets as env vars)
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

# ---------------------------------------------------------------------------
# Close CRM config
# ---------------------------------------------------------------------------
CLOSE_API_KEY = os.environ.get("CLOSE_API_KEY", "")
BASE_URL = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(f"{CLOSE_API_KEY}:".encode()).decode()

# Sending identity is resolved at runtime from the org's connected accounts.
# It used to be a hardcoded emailacct_ id paired with christian@scrubsquads.com;
# neither exists in this org any more, so every sequence_subscription POST
# failed and no lead was ever enrolled despite 7 active sequences.
SENDER_ACCOUNT_ID = None
SENDER_EMAIL = None
SENDER_NAME = None

# Dry-run state. When DRY_RUN is on, close_post() records the intended write
# instead of sending it, so a full sync can be rehearsed against live Sheets
# data without creating anything in Close.
DRY_RUN = False
DRY_RUN_LOG = []

# Reuse the curated blacklist instead of maintaining a second copy here.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from close_classify_new_leads import classify as classify_badfit
except Exception as _e:  # pragma: no cover
    logging.warning("Classifier unavailable (%s); bad-fit screen disabled", _e)
    classify_badfit = lambda name: ("KEEP", "")

# Miami-Dade, Broward (incl. the 754 overlay), Monroe and Palm Beach.
SOUTH_FL_AREA_CODES = {"305", "786", "954", "561", "754"}


def _load_protected():
    """Current clients that must never be cold-contacted. See
    configs/do_not_email.txt. Applied here too so a client resurfacing in a
    future scrape cannot be created and enrolled as a fresh lead."""
    p = Path(__file__).resolve().parent.parent / "configs" / "do_not_email.txt"
    if not p.exists():
        return []
    return [ln.strip().lower() for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


PROTECTED = _load_protected()

# The Leads sheet stores region as "Miami-Dade County, FL, USA", but the Close
# Region field is a choices field accepting only these values. Passing the raw
# sheet string through creates junk choices.
REGION_MAP = {
    "miami-dade": "Miami-Dade",
    "broward": "Broward",
    "homestead": "Homestead",
    "key largo": "Key Largo",
    "monroe": "Key Largo",
}


def map_region(raw):
    """Normalize a sheet region string onto a valid Close choice, or ''."""
    r = str(raw or "").lower()
    for needle, choice in REGION_MAP.items():
        if needle in r:
            return choice
    return ""

# Lead status
NEW_LEAD_STATUS = "stat_d857QdxZmTJKNUcl1XZMPcLgIG8BcQCylkQqiHstS2q"
IN_HOUSE_STATUS_LABEL = "In-House"  # ID looked up at runtime via status endpoint

# Sequences — industry-specific outreach, replaces the old single generic
# "Commercial" sequence (deleted 2026-08-30 as part of the industry-outreach
# migration; see .tmp/SESSION_HANDOFF.md). Each industry has its own email
# sequence now; Industry values that don't match a specific one fall back to
# the new Commercial catch-all rather than a sequence that no longer exists.
SEQ_BY_INDUSTRY = {
    "Property Management": "seq_1cB6ULpeSvoD5rKt9o5Rzu",
    "Real Estate": "seq_1kcWh8ObaVksKKZ1KL0Lns",
    "Construction": "seq_16UaJSNyYJlsaznOM9kPgD",
    "Healthcare": "seq_1vnZAqssyuYviZI4byD4KU",
    "Warehouse": "seq_1q2Gd2Ckaofo5ZtBOlFYqu",
    "Education": "seq_4RJzLUfIitjgtjJus682KO",
}
SEQ_COMMERCIAL_CATCHALL = "seq_3PIwJBhOUb3c3yyR45yOd7"
SEQ_EDUCATION = "seq_4RJzLUfIitjgtjJus682KO"  # kept for any other reference

EDUCATION_INDUSTRIES = {"Education"}

# Companies with more than this many employees almost always have in-house
# cleaning staff and don't convert. Auto-route them to In-House on sync.
MAX_COMPANY_SIZE_FOR_NEW_LEAD = int(os.environ.get("MAX_COMPANY_SIZE", "50"))

# ---------------------------------------------------------------------------
# Close API helpers
# ---------------------------------------------------------------------------
def close_get(path):
    req = urllib.request.Request(
        f"{BASE_URL}/{path}",
        headers={"Authorization": AUTH}
    )
    resp = urllib.request.urlopen(req)
    time.sleep(0.3)
    return json.loads(resp.read().decode())


def close_post(path, data):
    # Single choke point for every write this tool makes. In dry-run we return
    # a plausible fake response so the rest of the pipeline exercises normally
    # without touching Close.
    if DRY_RUN:
        DRY_RUN_LOG.append((path, data))
        if path == "lead/":
            return {
                "id": f"lead_DRYRUN{len(DRY_RUN_LOG):05d}",
                "display_name": data.get("name", ""),
                "custom": data.get("custom", {}),
                "contacts": [
                    {"id": f"cont_DRYRUN{i}", **c}
                    for i, c in enumerate(data.get("contacts", []))
                ],
            }
        return {"id": f"obj_DRYRUN{len(DRY_RUN_LOG):05d}"}

    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", data=body, method="POST",
        headers={"Authorization": AUTH, "Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        time.sleep(0.4)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        logger.error("  ERROR %d: %s", e.code, err[:300])
        return None


# ---------------------------------------------------------------------------
# Google Sheets helpers (reuse existing patterns)
# ---------------------------------------------------------------------------
def get_sheets_client():
    import gspread
    sa_json = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    return gspread.service_account_from_dict(sa_json)


def read_all_leads(spreadsheet):
    """Read all leads from the Leads tab as list of dicts."""
    ws = spreadsheet.worksheet("Leads")
    return ws.get_all_records()


def read_all_contacts(spreadsheet):
    """Read all contacts from the Contacts tab as list of dicts."""
    ws = spreadsheet.worksheet("Contacts")
    return ws.get_all_records()


# ---------------------------------------------------------------------------
# Close CRM field discovery
# ---------------------------------------------------------------------------
def get_custom_field_map():
    """Get a map of custom field name → field API key (e.g., 'custom.cf_xxx')."""
    fields = close_get("custom_field/lead/")
    field_map = {}
    for f in fields["data"]:
        # Close uses 'custom.cf_xxx' format for setting values
        field_map[f["name"]] = f"custom.{f['id']}"
    return field_map


def get_status_id(label):
    """Look up a lead status ID by its label."""
    data = close_get("status/lead/")
    for s in data.get("data", []):
        if s["label"] == label:
            return s["id"]
    raise RuntimeError(f"Lead status '{label}' not found in Close")


def normalize_phone(raw):
    """10-digit US form, or None. Shared by dedup and the market screen."""
    d = "".join(c for c in str(raw or "") if c.isdigit())
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else None


def get_existing_leads_dedup():
    """Get place_ids, lead names AND phone numbers from Close for dedup.

    Returns (place_ids: set, lead_names: set, phones: set).

    Phone matching matters because name matching only catches exact strings.
    "reef construction group" and "Reef Construction Group LLC" are the same
    business on the same number, and name-only dedup created both.
    """
    place_ids = set()
    lead_names = set()
    phones = set()
    has_more = True
    offset = 0

    # Get the Place ID custom field ID
    fields = close_get("custom_field/lead/")
    place_id_field = None
    for f in fields["data"]:
        if f["name"] == "Place ID":
            place_id_field = f["id"]
            break

    field_param = f",custom.{place_id_field}" if place_id_field else ""

    while has_more:
        data = close_get(
            f"lead/?_limit=200&_skip={offset}"
            f"&_fields=display_name,contacts{field_param}")
        for lead in data.get("data", []):
            # Collect place_id if set.
            # NOTE: when the request uses _fields, Close returns custom fields
            # ONLY as flat top-level keys ("custom.cf_xxx") and omits the
            # nested "custom" dict entirely. Reading lead["custom"] here silently
            # yielded {} on every lead, so Place ID dedup never fired and the
            # sync fell back to name-only matching (source of duplicate leads).
            if place_id_field:
                pid = lead.get(f"custom.{place_id_field}", "")
                if pid:
                    place_ids.add(str(pid).strip())
            # Collect lead name (normalized lowercase for matching)
            name = lead.get("display_name", "").strip().lower()
            if name:
                lead_names.add(name)
            # Collect every phone on the lead
            for c in lead.get("contacts", []) or []:
                for p in c.get("phones", []) or []:
                    n = normalize_phone(p.get("phone"))
                    if n:
                        phones.add(n)
        has_more = data.get("has_more", False)
        offset += 200

    return place_ids, lead_names, phones


# ---------------------------------------------------------------------------
# Lead creation
# ---------------------------------------------------------------------------
def split_name(full_name):
    """Split 'John Smith' into ('John', 'Smith')."""
    parts = str(full_name).strip().split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    elif len(parts) == 1:
        return parts[0], ""
    return "", ""


def build_address(full_address):
    """Parse a full address into Close address fields (best effort)."""
    # Close expects structured address, but we'll use the display field
    if not full_address:
        return {}
    return {
        "addresses": [{
            "label": "business",
            "address_1": str(full_address),
            "country": "US",
        }]
    }


def _max_company_size(contacts):
    """Return the largest company_size across the lead's contacts.

    Returns None if no contact has a numeric size (Apollo had no data).
    """
    sizes = []
    for c in contacts:
        raw = c.get("company_size", "")
        if raw == "" or raw is None:
            continue
        try:
            sizes.append(int(float(str(raw))))
        except (ValueError, TypeError):
            continue
    return max(sizes) if sizes else None


def create_lead_in_close(lead, contacts, field_map, in_house_status_id):
    """Create a lead in Close with contacts. Returns (lead_data, first_contact_id, routed_to_in_house).

    Leads where Apollo reports >MAX_COMPANY_SIZE_FOR_NEW_LEAD employees are
    routed directly to "In-House" status instead of "New Lead", so they
    never enter the active outreach funnel.
    """

    # Determine routing based on company size (defaults to New Lead if unknown)
    company_size = _max_company_size(contacts)
    is_too_big = (
        company_size is not None
        and company_size > MAX_COMPANY_SIZE_FOR_NEW_LEAD
    )
    status_id = in_house_status_id if is_too_big else NEW_LEAD_STATUS

    # Build custom fields
    custom = {}
    field_mappings = {
        "Region": map_region(lead.get("region", "")),
        "Place ID": lead.get("place_id", ""),
        "Google Maps Link": lead.get("google_maps_link", ""),
    }
    if company_size is not None:
        field_mappings["Company Size"] = company_size

    # Map business_type to Industry
    btype = lead.get("business_type", "")
    if btype:
        # Map scrape query types to Close industry values
        industry_map = {
            "Medical Offices": "Healthcare",
            "Property Management Companies": "Property Management",
            "Construction Companies": "Construction",
            "Schools": "Education",
            "Assisted Living": "Assisted Living",
            "Car Dealerships": "Car Dealerships",
            "Fitness Centers": "Fitness Centers",
            "Hotels": "Hospitality",
            "Warehouses": "Warehouse",
            "Office Buildings": "Commercial Building",
            "Retail Stores": "Retail",
        }
        industry = industry_map.get(btype, btype)
        field_mappings["Industry"] = industry

    # Also check contact-level industry from Apollo
    if contacts and not field_mappings.get("Industry"):
        apollo_industry = contacts[0].get("company_industry", "")
        if apollo_industry:
            field_mappings["Industry"] = apollo_industry

    for field_name, value in field_mappings.items():
        if value and field_name in {k.replace("custom.", ""): k for k in field_map}.values():
            pass  # will set below
        field_key = field_map.get(field_name)
        if field_key and value:
            # field_key is "custom.cf_xxx", we need just "cf_xxx" for the custom dict
            cf_id = field_key.replace("custom.", "")
            custom[cf_id] = str(value)

    # Build lead payload
    lead_data = {
        "name": lead.get("business_name", "Unknown"),
        "status_id": status_id,
        "custom": custom,
    }

    # Add URL
    website = lead.get("website", "")
    if website:
        if not website.startswith("http"):
            website = "https://" + website
        lead_data["url"] = website

    # Add addresses
    address = lead.get("full_address", "")
    if address:
        lead_data["addresses"] = [{"address_1": str(address), "country": "US"}]

    # Build contacts
    close_contacts = []
    for c in contacts:
        first, last = split_name(c.get("full_name", ""))
        contact = {
            "name": c.get("full_name", ""),
            "title": c.get("title", ""),
        }
        if first:
            contact["first_name"] = first
        if last:
            contact["last_name"] = last

        # Add email
        email = c.get("email", "")
        if email:
            contact["emails"] = [{"email": str(email), "type": "office"}]

        # Add phone.
        # Apollo contact numbers belong to a PERSON, so they are direct lines,
        # not the company switchboard. Typing them "office" (as this did) threw
        # away the only signal distinguishing a reachable line from a main
        # number, which is why SMS to these leads bounces ~56% of the time.
        # Full mobile-vs-landline detection needs Apollo's phone `type` carried
        # through the Contacts sheet - see phone_type note in the module docstring.
        phone = c.get("phone", "")
        if phone:
            contact["phones"] = [{"phone": str(phone), "type": "direct"}]

        close_contacts.append(contact)

    # If no contacts from Apollo, add a bare contact with business phone/email.
    # This one genuinely IS the company main line from Outscraper, so "office"
    # is correct here.
    if not close_contacts:
        bare = {"name": lead.get("business_name", "")}
        if lead.get("phone"):
            bare["phones"] = [{"phone": str(lead["phone"]), "type": "office"}]
        if lead.get("email"):
            bare["emails"] = [{"email": str(lead["email"]), "type": "office"}]
        close_contacts.append(bare)

    lead_data["contacts"] = close_contacts

    # Create in Close
    result = close_post("lead/", lead_data)
    if not result:
        return None, None, False

    # Get a contact to subscribe to the email sequence.
    #
    # This used to fall back to contacts[0] when nobody had an email, which
    # queued a subscription for a contact with nowhere to send. In a dry run
    # of 428 leads that meant 428 subscriptions against only 72 real email
    # addresses. No email, no subscription.
    first_contact_id = None
    for contact in result.get("contacts") or []:
        if contact.get("emails"):
            first_contact_id = contact["id"]
            break

    return result, first_contact_id, is_too_big


def resolve_sender():
    """Find a connected account in this org that can actually send email.

    Returns (account_id, email, display_name). Raises if none is available,
    because silently continuing means sequence subscriptions fail one by one
    with nothing to show for it.
    """
    global SENDER_ACCOUNT_ID, SENDER_EMAIL, SENDER_NAME
    if SENDER_ACCOUNT_ID:
        return SENDER_ACCOUNT_ID, SENDER_EMAIL, SENDER_NAME

    data = close_get("connected_account/")
    for a in data.get("data", []):
        if "email_sending" in (a.get("enabled_features") or []):
            SENDER_ACCOUNT_ID = a["id"]
            SENDER_EMAIL = a.get("email", "")
            identity = a.get("default_identity") or {}
            SENDER_NAME = identity.get("name") or SENDER_EMAIL.split("@")[0]
            return SENDER_ACCOUNT_ID, SENDER_EMAIL, SENDER_NAME

    raise RuntimeError(
        "No connected account in this org has email_sending enabled. "
        "Connect a sending address in Close before syncing."
    )


def subscribe_to_sequence(contact_id, sequence_id):
    """Subscribe a contact to an email sequence."""
    if not contact_id:
        return False
    account_id, email, name = resolve_sender()
    result = close_post("sequence_subscription/", {
        "sequence_id": sequence_id,
        "contact_id": contact_id,
        "sender_account_id": account_id,
        "sender_name": name,
        "sender_email": email,
    })
    return result is not None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global DRY_RUN

    ap = argparse.ArgumentParser(description="Sync leads from Google Sheets to Close CRM")
    ap.add_argument("--dry-run", action="store_true",
                    help="Rehearse the sync without writing anything to Close.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process at most N new leads (useful with --dry-run).")
    ap.add_argument("--max-subscriptions", type=int, default=None,
                    help=("Enroll at most N contacts in email sequences. Leads "
                          "are still created. Creating clean records and "
                          "starting a cold campaign are separate decisions, "
                          "and a domain with no cold-send history should ramp "
                          "slowly rather than open with 128 messages."))
    ap.add_argument("--no-subscribe", action="store_true",
                    help="Create leads only. No sequence enrollment at all.")
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    if not CLOSE_API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        sys.exit(1)
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON not set")
        sys.exit(1)

    print("=" * 60)
    print("Close CRM Sync — Google Sheets -> Close")
    if DRY_RUN:
        print("*** DRY RUN — no writes will be made ***")
    print("=" * 60)

    # Fail fast on the sending identity rather than discovering it lead by lead
    try:
        acct, email, name = resolve_sender()
        print(f"  Sender resolved: {name} <{email}>  ({acct})")
    except RuntimeError as e:
        print(f"  WARNING: {e}")
        print("  Leads will still be created; sequence subscriptions will be skipped.")

    # 1. Get custom field map and In-House status ID from Close
    print("\nLoading Close custom fields...")
    field_map = get_custom_field_map()
    print(f"  Found {len(field_map)} custom fields")
    in_house_status_id = get_status_id(IN_HOUSE_STATUS_LABEL)
    print(f"  Big-company auto-route threshold: >{MAX_COMPANY_SIZE_FOR_NEW_LEAD} employees -> In-House")

    # 2. Get existing leads from Close (for dedup by place_id + name)
    print("Loading existing leads from Close...")
    existing_pids, existing_names, existing_phones = get_existing_leads_dedup()
    print(f"  {len(existing_pids)} with Place ID, {len(existing_names)} names, "
          f"{len(existing_phones)} phone numbers")

    # 3. Read leads + contacts from Google Sheets
    print("Reading Google Sheets...")
    client = get_sheets_client()
    spreadsheet = client.open_by_key(os.environ["GOOGLE_SHEET_ID"])

    all_leads = read_all_leads(spreadsheet)
    all_contacts = read_all_contacts(spreadsheet)
    print(f"  Leads tab: {len(all_leads)} rows")
    print(f"  Contacts tab: {len(all_contacts)} rows")

    # Build contact lookup by place_id
    contacts_by_pid = {}
    for c in all_contacts:
        pid = str(c.get("place_id", "")).strip()
        if pid:
            contacts_by_pid.setdefault(pid, []).append(c)

    # 4. Find new leads not already in Close, and screen out the ones that
    #    should never have been queued in the first place.
    #
    #    A dry run of this sync before these screens existed would have created
    #    428 leads including 21 phone-duplicates of existing records, 45
    #    duplicates within the batch itself, 16 leads the classifier already
    #    rejects (Baptist Health, Mount Sinai, Jackson Memorial, the Florida
    #    Department of Health), 46 out-of-market numbers and 24 toll-free.
    new_leads = []
    skipped_pid = 0
    skipped_name = 0
    skipped_phone = 0
    skipped_badfit = []
    skipped_protected = []
    skipped_market = 0
    batch_phones = set()

    for lead in all_leads:
        pid = str(lead.get("place_id", "")).strip()
        raw_name = str(lead.get("business_name", "")).strip()
        name = raw_name.lower()
        phone = normalize_phone(lead.get("phone"))

        if pid and pid in existing_pids:
            skipped_pid += 1
            continue
        if name and name in existing_names:
            skipped_name += 1
            continue

        # Same number already on a lead in Close, or earlier in this batch
        if phone and (phone in existing_phones or phone in batch_phones):
            skipped_phone += 1
            continue

        blob = f"{raw_name} {lead.get('email', '')} {lead.get('website', '')}".lower()
        prot = next((p for p in PROTECTED if p in blob), None)
        if prot:
            skipped_protected.append(f"{raw_name} [matched '{prot}']")
            continue

        verdict, reason = classify_badfit(raw_name)
        if verdict == "DEFINITE_BAD":
            skipped_badfit.append(f"{raw_name} [{reason}]")
            continue

        # Copy and service area are South Florida. A toll-free or out-of-state
        # number is either unreachable or not a local buyer.
        if phone and phone[:3] not in SOUTH_FL_AREA_CODES:
            skipped_market += 1
            continue

        if pid:
            if phone:
                batch_phones.add(phone)
            new_leads.append(lead)

    print(f"\n  Skipped (Place ID match):   {skipped_pid}")
    print(f"  Skipped (name match):       {skipped_name}")
    print(f"  Skipped (phone duplicate):  {skipped_phone}")
    print(f"  Skipped (protected client): {len(skipped_protected)}")
    print(f"  Skipped (bad fit):          {len(skipped_badfit)}")
    print(f"  Skipped (out of market):    {skipped_market}")
    print(f"  New leads to sync:          {len(new_leads)}")
    if skipped_badfit:
        print("\n  Bad-fit leads screened out:")
        for b in skipped_badfit[:20]:
            print(f"    - {b}")
        if len(skipped_badfit) > 20:
            print(f"    ... and {len(skipped_badfit) - 20} more")

    if not new_leads:
        print("Nothing to sync. All leads already in Close.")
        return

    if args.limit:
        print(f"  --limit {args.limit}: processing first {args.limit} of {len(new_leads)}")
        new_leads = new_leads[:args.limit]

    # 5. Create leads in Close
    print(f"\nSyncing {len(new_leads)} leads to Close...")
    created = 0
    subscribed = 0
    routed_in_house = 0
    subscription_capped = 0
    errors = 0

    for i, lead in enumerate(new_leads):
        pid = str(lead.get("place_id", "")).strip()
        contacts = contacts_by_pid.get(pid, [])
        name = lead.get("business_name", "?")

        result, contact_id, routed = create_lead_in_close(
            lead, contacts, field_map, in_house_status_id
        )
        if result:
            created += 1
            if routed:
                routed_in_house += 1

            # Skip sequence subscription for big-co leads (they're In-House now)
            if not routed:
                # Read the industry back defensively: Close returns custom
                # fields as a nested dict on some responses and as flat
                # "custom.cf_xxx" keys on others, depending on _fields.
                ind_key = field_map.get("Industry", "")
                ind_id = ind_key.replace("custom.", "")
                industry = (
                    result.get(ind_key)
                    or (result.get("custom") or {}).get(ind_id, "")
                    or ""
                )
                if industry in EDUCATION_INDUSTRIES:
                    seq_id = SEQ_EDUCATION
                else:
                    seq_id = SEQ_BY_INDUSTRY.get(industry, SEQ_COMMERCIAL_CATCHALL)

                at_cap = (args.max_subscriptions is not None
                          and subscribed >= args.max_subscriptions)
                if contact_id and not args.no_subscribe and not at_cap:
                    if subscribe_to_sequence(contact_id, seq_id):
                        subscribed += 1
                elif contact_id and at_cap:
                    subscription_capped += 1

            if (i + 1) % 25 == 0:
                print(f"  Progress: {i + 1}/{len(new_leads)} "
                      f"({created} created, {subscribed} subscribed, "
                      f"{routed_in_house} auto-routed to In-House)")
        else:
            errors += 1
            logger.error("  Failed to create: %s", name)

    # 6. Summary
    print(f"\n{'=' * 60}")
    print("SYNC COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Total created: {created}")
    print(f"    - New Lead (active funnel): {created - routed_in_house}")
    print(f"    - Auto-routed to In-House (>{MAX_COMPANY_SIZE_FOR_NEW_LEAD} employees): {routed_in_house}")
    print(f"  Subscribed to sequences: {subscribed}")
    if subscription_capped:
        print(f"    - held back by --max-subscriptions: {subscription_capped} "
              f"(emailable, not yet enrolled)")
    if args.no_subscribe:
        print("    - --no-subscribe: sequence enrollment skipped entirely")
    print(f"  Errors: {errors}")
    print(f"  Already in Close (skipped): {len(existing_pids)}")

    if DRY_RUN:
        import collections
        by_path = collections.Counter(p for p, _ in DRY_RUN_LOG)
        print(f"\n{'=' * 60}")
        print("DRY RUN — writes that were suppressed")
        print(f"{'=' * 60}")
        for path, n in by_path.most_common():
            print(f"  POST {path:<24} x{n}")

        phone_types = collections.Counter()
        with_pid = 0
        for path, payload in DRY_RUN_LOG:
            if path != "lead/":
                continue
            if payload.get("custom", {}).get(
                    field_map.get("Place ID", "").replace("custom.", "")):
                with_pid += 1
            for c in payload.get("contacts", []):
                for ph in c.get("phones", []):
                    phone_types[ph.get("type")] += 1
        lead_writes = by_path.get("lead/", 0)
        print(f"\n  leads carrying a Place ID: {with_pid}/{lead_writes}"
              f"   <- 0 here means dedup will still be blind next run")
        print(f"  phone types that would be written: {dict(phone_types)}")
        out = Path(".tmp/close_sync_dryrun.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(DRY_RUN_LOG, indent=2), encoding="utf-8")
        print(f"  full payload log: {out}")


if __name__ == "__main__":
    main()
