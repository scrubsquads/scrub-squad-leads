"""Google Sheets client for Scrub Squad Lead Generator.

All Sheets I/O lives here: authentication, worksheet creation,
reading existing place_ids, batch appending leads, and logging runs.
No business logic — only transport.
"""

import json
import logging
import os

import gspread
from gspread.exceptions import WorksheetNotFound

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema definitions — column order MUST match the Google Sheet headers.
# ---------------------------------------------------------------------------
LEADS_HEADERS = [
    "place_id",
    "business_name",
    "business_type",
    "region",
    "full_address",
    "phone",
    "email",
    "website",
    "rating",
    "reviews_count",
    "google_maps_link",
    "query_used",
    "pulled_at",
    "run_date",
]

RUN_LOG_HEADERS = [
    "run_date",
    "started_at",
    "finished_at",
    "duration_seconds",
    "total_scraped",
    "new_appended",
    "dupes_skipped",
    "queries_attempted",
    "queries_succeeded",
    "queries_failed",
    "status",
    "errors",
]

CONTACTS_HEADERS = [
    "apollo_id",
    "full_name",
    "title",
    "seniority",
    "email",
    "phone",
    "linkedin_url",
    "company_name",
    "company_industry",
    "company_website",
]

ENRICHMENT_LOG_HEADERS = [
    "run_date",
    "started_at",
    "finished_at",
    "duration_seconds",
    "leads_processed",
    "leads_skipped_no_data",
    "contacts_found",
    "contacts_enriched",
    "credits_used",
    "batch_size",
    "dry_run",
    "status",
    "errors",
]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def get_client():
    """Authenticate via service account JSON stored in env var.

    The JSON is parsed in memory — nothing is written to disk.
    """
    sa_json = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    return gspread.service_account_from_dict(sa_json)


# ---------------------------------------------------------------------------
# Worksheet helpers
# ---------------------------------------------------------------------------
def get_or_create_worksheet(spreadsheet, name, headers):
    """Open a worksheet by name, or create it with the given headers.

    Idempotent: if the worksheet already exists its headers are NOT
    re-written.  Tab names are case-sensitive — "Leads" != "leads".
    """
    try:
        ws = spreadsheet.worksheet(name)
        logger.info("Opened existing worksheet: %s", name)
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=name, rows=1000, cols=len(headers)
        )
        ws.update("A1", [headers])
        logger.info("Created worksheet '%s' with %d columns", name, len(headers))
    return ws


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def read_existing_place_ids(worksheet):
    """Return a set of all place_id values currently in the worksheet.

    Reads column A in a single API call.  Strips the header row.
    """
    values = worksheet.col_values(1)
    if values:
        values = values[1:]  # drop header
    return set(values)


def read_existing_enriched_company_names(worksheet):
    """Return a set of company_name values already in the Contacts tab.

    Reads column H (company_name) in a single API call.  Strips the header.
    Used to skip companies that have already been enriched.
    """
    values = worksheet.col_values(8)  # column H = company_name
    if values:
        values = values[1:]  # drop header
    return set(v.strip().lower() for v in values if v.strip())


def read_leads_for_enrichment(worksheet):
    """Read all leads with the columns needed for Apollo enrichment.

    Returns a list of dicts with keys: place_id, business_name, website.
    Skips rows with an empty place_id.
    """
    records = worksheet.get_all_records()
    return [
        {
            "place_id":      str(r.get("place_id", "")).strip(),
            "business_name": str(r.get("business_name", "")).strip(),
            "website":       str(r.get("website", "")).strip(),
        }
        for r in records
        if str(r.get("place_id", "")).strip()
    ]


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
def append_leads(worksheet, leads):
    """Batch-append a list of lead dicts as rows.

    Column order matches LEADS_HEADERS exactly.  A single append_rows()
    call is made regardless of how many leads are passed.
    """
    if not leads:
        return

    rows = []
    for lead in leads:
        rows.append([lead.get(h, "") for h in LEADS_HEADERS])

    worksheet.append_rows(rows, value_input_option="RAW")
    logger.info("Appended %d leads to '%s'", len(rows), worksheet.title)


def log_run(worksheet, summary):
    """Append one summary row to the Run_Log worksheet.

    Column order matches RUN_LOG_HEADERS exactly.
    """
    row = [summary.get(h, "") for h in RUN_LOG_HEADERS]
    worksheet.append_row(row, value_input_option="RAW")
    logger.info("Logged run summary to '%s'", worksheet.title)


def append_contacts(worksheet, contacts):
    """Batch-append contact dicts as rows to the Contacts tab.

    Column order matches CONTACTS_HEADERS exactly.
    """
    if not contacts:
        return

    rows = []
    for contact in contacts:
        rows.append([contact.get(h, "") for h in CONTACTS_HEADERS])

    worksheet.append_rows(rows, value_input_option="RAW")
    logger.info("Appended %d contacts to '%s'", len(rows), worksheet.title)


def log_enrichment_run(worksheet, summary):
    """Append one summary row to the Enrichment_Log worksheet.

    Column order matches ENRICHMENT_LOG_HEADERS exactly.
    """
    row = [summary.get(h, "") for h in ENRICHMENT_LOG_HEADERS]
    worksheet.append_row(row, value_input_option="RAW")
    logger.info("Logged enrichment summary to '%s'", worksheet.title)
