"""Deduplication filter for Scrub Squad Lead Generator.

Compares scraped leads against the set of place_ids already present
in the Google Sheet.  Pure logic — no API calls, no side effects.
"""

import logging

logger = logging.getLogger(__name__)


def filter_new_leads(leads, existing_place_ids):
    """Remove leads whose place_id is already in the Sheet.

    Args:
        leads:               list of normalized lead dicts (from scrape_leads)
        existing_place_ids:  set of place_id strings already in the Sheet
                             (from sheets.read_existing_place_ids)

    Returns:
        (new_leads, dupes_count)
            – new_leads:   leads not yet in the Sheet
            – dupes_count: number of leads that were filtered out
    """
    new_leads = []
    dupes_count = 0

    for lead in leads:
        if lead["place_id"] in existing_place_ids:
            dupes_count += 1
        else:
            new_leads.append(lead)

    logger.info("Dedup result: %d new, %d duplicates skipped", len(new_leads), dupes_count)
    return new_leads, dupes_count
