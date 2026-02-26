"""Apollo.io API client for Scrub Squad Contact Enrichment.

Handles people search (FREE), people enrichment (1 credit each),
domain extraction, smart title ranking, and field normalization.
"""

import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://api.apollo.io/api/v1"
MAX_RETRIES = 3
BACKOFF_BASE = 2          # seconds — delays: 2, 4, 8
INTER_SEARCH_DELAY = 1    # seconds between search calls (free)
INTER_ENRICH_DELAY = 6    # seconds between enrichment calls (600/hour limit)

# Titles that directly handle cleaning/facility vendor decisions.
# Used to rank search results — higher index = lower priority.
TITLE_PRIORITY = [
    "facility manager",
    "director of facilities",
    "facilities director",
    "building manager",
    "maintenance manager",
    "director of maintenance",
    "property manager",
    "office manager",
    "operations manager",
    "director of operations",
    "general manager",
    # Executive titles ranked last — relevant only at small companies
    "owner",
    "ceo",
    "president",
    "founder",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def extract_domain(website_url):
    """Extract the root domain from a website URL.

    Handles URLs with/without scheme, with/without www prefix,
    and URLs with paths.  Returns None if input is empty.

    Examples:
        "https://www.example.com/about" -> "example.com"
        "http://example.com"            -> "example.com"
        "example.com"                   -> "example.com"
        ""                              -> None
    """
    if not website_url or not website_url.strip():
        return None

    url = website_url.strip()

    # Add scheme if missing so urlparse works correctly
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    domain = (parsed.hostname or "").lower().strip()

    if not domain:
        return None

    # Strip www. prefix
    if domain.startswith("www."):
        domain = domain[4:]

    # Skip social media / directory URLs — not company domains
    skip_domains = {
        "facebook.com", "instagram.com", "twitter.com", "x.com",
        "linkedin.com", "yelp.com", "yellowpages.com", "bbb.org",
        "google.com", "youtube.com", "tiktok.com",
    }
    if domain in skip_domains:
        return None

    return domain


def search_people(api_key, domain=None, company_name=None,
                  titles=None, seniorities=None, per_page=10):
    """Search for people at a company via Apollo People Search (FREE).

    Uses domain lookup if available, falls back to company name.

    Args:
        api_key:       Apollo API key
        domain:        Company domain (preferred)
        company_name:  Fallback company name (fuzzy match)
        titles:        List of target job titles
        seniorities:   List of seniority levels
        per_page:      Max results to return

    Returns:
        list[dict] — Raw Apollo person objects from the ``people`` array.
    """
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "x-api-key": api_key,
    }

    body = {
        "per_page": per_page,
        "page": 1,
    }

    if domain:
        body["q_organization_domains_list"] = [domain]
    elif company_name:
        body["q_organization_name"] = company_name
    else:
        return []

    if titles:
        body["person_titles"] = titles
    if seniorities:
        body["person_seniorities"] = seniorities

    url = f"{BASE_URL}/mixed_people/api_search"
    data = _request_with_retry("POST", url, headers, json_body=body)
    return data.get("people", [])


def enrich_person(api_key, person_id):
    """Enrich a single person by Apollo ID — costs 1 CREDIT.

    Reveals email address and phone number.

    Args:
        api_key:    Apollo API key
        person_id:  Apollo person ID from search results

    Returns:
        dict — Full Apollo person object with contact details.
    """
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "x-api-key": api_key,
    }

    body = {
        "id": person_id,
        "reveal_personal_emails": True,
    }

    url = f"{BASE_URL}/people/match"
    data = _request_with_retry("POST", url, headers, json_body=body)
    return data.get("person", {})


def rank_contacts(people, max_contacts, small_company_threshold):
    """Rank and select the best decision-makers from search results.

    Prioritizes facility/operations titles over executives.
    Filters out executives (Owner/CEO/President) at larger companies.

    Args:
        people:                    List of raw Apollo person dicts
        max_contacts:              Max contacts to return
        small_company_threshold:   Employee count below which executives
                                   are considered relevant

    Returns:
        list[dict] — Top-ranked people, at most ``max_contacts``.
    """
    if not people:
        return []

    scored = []
    for person in people:
        title = (person.get("title") or "").lower()
        seniority = (person.get("seniority") or "").lower()

        # Determine company size (may not always be available)
        org = person.get("organization") or {}
        emp_count = org.get("estimated_num_employees") or 0
        if isinstance(emp_count, str):
            try:
                emp_count = int(emp_count)
            except ValueError:
                emp_count = 0

        # Skip executives at large companies
        is_executive = seniority in ("owner", "founder", "c_suite") or \
            any(t in title for t in ("owner", "ceo", "president", "founder"))
        if is_executive and emp_count > small_company_threshold:
            logger.debug("Skipping executive '%s' at large company (%d employees)",
                         person.get("title"), emp_count)
            continue

        # Score: lower = better.  Match against priority list.
        score = len(TITLE_PRIORITY)  # default: worst score
        for i, priority_title in enumerate(TITLE_PRIORITY):
            if priority_title in title:
                score = i
                break

        # Prefer people who have email available
        has_email = person.get("has_email", False)
        if not has_email:
            score += 100  # deprioritize heavily

        scored.append((score, person))

    scored.sort(key=lambda x: x[0])
    return [person for _, person in scored[:max_contacts]]


def normalize_contact(person, place_id, business_name, enrichment_source,
                      run_date, fallback_phone=""):
    """Map an enriched Apollo person to our Contacts schema.

    Args:
        person:             Full Apollo person dict (from enrich_person)
        place_id:           Parent lead's place_id (foreign key)
        business_name:      Parent lead's business_name
        enrichment_source:  "domain_search" or "name_search"
        run_date:           Date string for this run
        fallback_phone:     Company phone from Outscraper (used if Apollo
                            has no direct phone for the contact)

    Returns:
        dict matching CONTACTS_HEADERS column order.
    """
    apollo_id = person.get("id", "")

    # Full name
    first = (person.get("first_name") or "").strip()
    last = (person.get("last_name") or "").strip()
    full_name = person.get("name", "").strip() or f"{first} {last}".strip()

    # Email — check nested contact object first, then top-level
    email = ""
    contact_info = person.get("contact") or {}
    contact_emails = contact_info.get("contact_emails") or []
    if contact_emails:
        email = contact_emails[0].get("email", "")
    if not email:
        email = person.get("email", "") or ""

    # Phone — check Apollo first, fall back to Outscraper company phone
    phone = ""
    phone_numbers = contact_info.get("phone_numbers") or []
    if phone_numbers:
        phone = phone_numbers[0].get("sanitized_number", "") or \
                phone_numbers[0].get("raw_number", "")
    if not phone:
        phone = fallback_phone or ""

    # Company info from Apollo's organization object
    org = person.get("organization") or {}
    company_name = (org.get("name") or business_name or "").strip()
    company_industry = (org.get("industry") or "").strip()
    company_website = (org.get("website_url") or "").strip()

    return {
        "place_id":          place_id,
        "apollo_id":         apollo_id,
        "full_name":         full_name,
        "title":             (person.get("title") or "").strip(),
        "seniority":         (person.get("seniority") or "").strip(),
        "email":             email.strip(),
        "phone":             phone.strip(),
        "linkedin_url":      (person.get("linkedin_url") or "").strip(),
        "company_name":      company_name,
        "company_industry":  company_industry,
        "company_website":   company_website,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _request_with_retry(method, url, headers, json_body=None):
    """HTTP request with exponential-backoff retries.

    Raises the last exception if all attempts are exhausted.
    """
    last_exc = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.request(
                method, url, headers=headers, json=json_body, timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0

            # Credit exhaustion — raise immediately, no retry
            if status == 402:
                logger.error("Apollo credits exhausted (HTTP 402)")
                raise

            # Rate limit — always retry
            if status == 429:
                wait = BACKOFF_BASE ** (attempt + 1)
                logger.warning("  Rate limited (429). Retrying in %ds…", wait)
                time.sleep(wait)
                last_exc = e
                continue

            # Other HTTP errors — retry with backoff
            last_exc = e
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                logger.warning("  HTTP %d on attempt %d. Retrying in %ds…",
                               status, attempt + 1, wait)
                time.sleep(wait)
            else:
                logger.error("  All %d attempts exhausted.", MAX_RETRIES)

        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                logger.warning("  Attempt %d failed: %s. Retrying in %ds…",
                               attempt + 1, e, wait)
                time.sleep(wait)
            else:
                logger.error("  All %d attempts exhausted.", MAX_RETRIES)

    raise last_exc
