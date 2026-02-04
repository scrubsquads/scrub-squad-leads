#!/usr/bin/env python3
"""Scrub Squad Lead Generator — Main Pipeline Orchestrator.

Reads configs/queries.yaml  →  scrapes leads via Outscraper  →
deduplicates against the existing Google Sheet  →  appends only new
leads  →  writes a run summary to the Run_Log worksheet.

Entry point for GitHub Actions.  Also runnable locally with the three
required environment variables set:
    OUTSCRAPER_API_KEY
    GOOGLE_SERVICE_ACCOUNT_JSON
    GOOGLE_SHEET_ID
"""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Path setup — allow importing sibling modules without a package __init__
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dedupe import filter_new_leads          # noqa: E402
from scrape_leads import scrape_all_queries  # noqa: E402
from sheets import (                         # noqa: E402
    LEADS_HEADERS,
    RUN_LOG_HEADERS,
    append_leads,
    get_client,
    get_or_create_worksheet,
    log_run,
    read_existing_place_ids,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def _load_config():
    """Load queries.yaml from configs/ relative to the repo root."""
    config_path = Path(__file__).resolve().parent.parent / "configs" / "queries.yaml"
    with open(config_path) as fh:
        return yaml.safe_load(fh)


def _build_queries(config):
    """Cross-join regions x business_types using query_template.

    Returns a list of dicts, each with keys: query, region, business_type.
    Example output element:
        {"query": "Medical Offices in Homestead, FL, USA",
         "region": "Homestead, FL, USA",
         "business_type": "Medical Offices"}
    """
    template = config["query_template"]
    queries = []
    for region in config["regions"]:
        for btype in config["business_types"]:
            queries.append({
                "query":         template.format(business_type=btype, location=region),
                "region":        region,
                "business_type": btype,
            })
    return queries


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    start_time = datetime.now(timezone.utc)
    run_date = start_time.strftime("%Y-%m-%d")

    # --- Config ---------------------------------------------------------------
    config  = _load_config()
    queries = _build_queries(config)
    limit   = config["settings"]["results_per_query"]
    lang    = config["settings"]["language"]

    logger.info("=" * 50)
    logger.info("Scrub Squad Lead Generator")
    logger.info("Run date: %s  |  Queries: %d  |  Limit: %d/query", run_date, len(queries), limit)
    logger.info("=" * 50)

    # --- Env vars -------------------------------------------------------------
    outscraper_key = os.environ.get("OUTSCRAPER_API_KEY")
    sa_json        = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id       = os.environ.get("GOOGLE_SHEET_ID")

    if not all([outscraper_key, sa_json, sheet_id]):
        logger.error(
            "Missing env vars. Required: OUTSCRAPER_API_KEY, "
            "GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID"
        )
        sys.exit(1)

    # --- Run summary (written in the finally block no matter what) ------------
    summary = {
        "run_date":           run_date,
        "started_at":         start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at":        "",
        "duration_seconds":   "",
        "total_scraped":      0,
        "new_appended":       0,
        "dupes_skipped":      0,
        "queries_attempted":  len(queries),
        "queries_succeeded":  0,
        "queries_failed":     0,
        "status":             "SUCCESS",
        "errors":             "",
    }

    run_log_ws = None  # set after successful Sheet connection

    try:
        # --- Google Sheets connection -----------------------------------------
        logger.info("Connecting to Google Sheets…")
        gc         = get_client()
        spreadsheet = gc.open_by_key(sheet_id)
        leads_ws   = get_or_create_worksheet(spreadsheet, "Leads",   LEADS_HEADERS)
        run_log_ws = get_or_create_worksheet(spreadsheet, "Run_Log", RUN_LOG_HEADERS)

        # --- Scrape -----------------------------------------------------------
        logger.info("Starting scrape…")
        raw_leads, errors = scrape_all_queries(queries, outscraper_key, limit, lang)

        summary["total_scraped"]      = len(raw_leads)
        summary["queries_failed"]     = len(errors)
        summary["queries_succeeded"]  = len(queries) - len(errors)
        if errors:
            summary["status"] = "PARTIAL_FAILURE"
            summary["errors"] = " | ".join(errors)

        logger.info("Scrape complete: %d leads, %d query failures", len(raw_leads), len(errors))

        # --- Dedupe -----------------------------------------------------------
        logger.info("Running deduplication…")
        existing_ids = read_existing_place_ids(leads_ws)
        logger.info("Existing place_ids in Sheet: %d", len(existing_ids))

        # Stamp run_date on every lead (constant for this run)
        for lead in raw_leads:
            lead["run_date"] = run_date

        new_leads, dupes_count = filter_new_leads(raw_leads, existing_ids)
        summary["new_appended"]   = len(new_leads)
        summary["dupes_skipped"]  = dupes_count

        # --- Append -----------------------------------------------------------
        if new_leads:
            logger.info("Appending %d new leads…", len(new_leads))
            append_leads(leads_ws, new_leads)
        else:
            logger.info("No new leads to append.")

    except Exception as exc:
        summary["status"] = "FAILED"
        summary["errors"] = str(exc)
        logger.error("Pipeline failed: %s", exc, exc_info=True)

    finally:
        # --- Always write run summary ----------------------------------------
        end_time = datetime.now(timezone.utc)
        summary["finished_at"]      = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        summary["duration_seconds"] = round((end_time - start_time).total_seconds(), 1)

        if run_log_ws is not None:
            try:
                log_run(run_log_ws, summary)
            except Exception as log_exc:
                logger.error("Failed to write Run_Log entry: %s", log_exc)

        # --- Print summary to stdout (captured by GitHub Actions log)--------
        logger.info("=" * 50)
        logger.info("Run Summary")
        logger.info("  Status:             %s", summary["status"])
        logger.info("  Total scraped:      %d", summary["total_scraped"])
        logger.info("  New appended:       %d", summary["new_appended"])
        logger.info("  Duplicates skipped: %d", summary["dupes_skipped"])
        logger.info("  Queries:            %d/%d succeeded",
                    summary["queries_succeeded"], summary["queries_attempted"])
        logger.info("  Duration:           %ss", summary["duration_seconds"])
        if summary["errors"]:
            logger.info("  Errors:             %s", summary["errors"])
        logger.info("=" * 50)

    # Non-zero exit on any failure → GitHub Actions marks the job red
    if summary["status"] != "SUCCESS":
        sys.exit(1)


if __name__ == "__main__":
    main()
