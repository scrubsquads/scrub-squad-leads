"""Outscraper API client for Scrub Squad Lead Generator.

Handles scraping, retry logic, rate-limit spacing, and field
normalization from Outscraper's response format into our schema.
"""

import hashlib
import logging
import time
from datetime import datetime, timezone

from outscraper import OutscraperClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
BACKOFF_BASE = 2       # seconds — delays: 2, 4, 8
INTER_QUERY_DELAY = 1  # seconds between successive queries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def scrape_all_queries(queries, api_key, limit, language):
    """Scrape every query, isolating failures per-query.

    Args:
        queries:   list of dicts with keys: query, region, business_type
        api_key:   Outscraper API key
        limit:     max results per query (from config)
        language:  language code (from config)

    Returns:
        (list[dict], list[str])
            – Flat list of normalized lead dicts.
            – List of human-readable error strings for failed queries.
    """
    client = OutscraperClient(api_key=api_key)
    all_leads = []
    errors = []

    for i, q in enumerate(queries):
        query_str = q["query"]
        logger.info("[%d/%d] Scraping: %s", i + 1, len(queries), query_str)

        try:
            raw_places = _scrape_single_query(client, query_str, limit, language)

            normalized = []
            for place in raw_places:
                lead = _normalize_lead(place, query_str, q["region"], q["business_type"])
                if lead is not None:
                    normalized.append(lead)

            all_leads.extend(normalized)
            logger.info("  -> %d leads returned (%d raw)", len(normalized), len(raw_places))

        except Exception as e:
            msg = f"Query '{query_str}' failed after {MAX_RETRIES} attempts: {e}"
            logger.error("  %s", msg)
            errors.append(msg)

        # Brief pause between queries to stay within rate limits
        if i < len(queries) - 1:
            time.sleep(INTER_QUERY_DELAY)

    return all_leads, errors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _scrape_single_query(client, query, limit, language):
    """Call Outscraper for one query with exponential-backoff retries.

    google_maps_search() returns an iterable of result-sets (one per
    query passed).  We pass exactly one query, so we consume one set.
    """
    last_exc = None

    for attempt in range(MAX_RETRIES):
        try:
            results = client.google_maps_search(
                [query],
                limit=limit,
                language=language,
                region="us",
            )
            # Flatten: results yields one list per query; we sent one query
            places = []
            for result_set in results:
                places.extend(result_set)
            return places

        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)  # 2 → 4 → 8
                logger.warning("  Attempt %d failed: %s. Retrying in %ds…", attempt + 1, e, wait)
                time.sleep(wait)
            else:
                logger.error("  All %d attempts exhausted.", MAX_RETRIES)

    raise last_exc  # pragma: no cover — loop always raises or returns


def _normalize_lead(raw, query_string, region, business_type):
    """Map one Outscraper result dict to our Leads schema.

    Returns None if the record cannot be reliably identified (missing
    place_id AND missing either name or phone for the fallback hash).
    """
    # --- Primary dedupe key -------------------------------------------------
    place_id = (raw.get("place_id") or raw.get("google_id") or "").strip()

    name = (raw.get("name") or "").strip()
    phone = (raw.get("phone") or "").strip()

    if not place_id:
        # Fallback key requires both name and phone
        if not name or not phone:
            logger.warning(
                "Dropping lead — no place_id and missing name or phone. "
                "Raw name: %s",
                raw.get("name", "<empty>"),
            )
            return None

        phone_clean = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        hash_input = f"{name.lower()}|{phone_clean}"
        place_id = "FALLBACK_" + hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        logger.debug("Generated fallback key for '%s': %s", name, place_id)

    # --- Google Maps link (only valid for real place_ids) -------------------
    if place_id.startswith("FALLBACK_"):
        google_maps_link = ""
    else:
        google_maps_link = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    # --- Email (Outscraper may return 'email' string or 'emails' list) ------
    emails = raw.get("emails", [])
    if isinstance(emails, list) and emails:
        email = str(emails[0]).strip()
    else:
        email = (raw.get("email") or "").strip()

    return {
        "place_id":         place_id,
        "business_name":    name,
        "business_type":    business_type,
        "region":           region,
        "full_address":     (raw.get("full_address") or "").strip(),
        "phone":            phone,
        "email":            email,
        "website":          (raw.get("site") or "").strip(),
        "rating":           raw.get("rating", ""),
        "reviews_count":    raw.get("reviews", ""),
        "google_maps_link": google_maps_link,
        "query_used":       query_string,
        "pulled_at":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_date":         "",  # stamped by run_pipeline.py (constant per run)
    }
