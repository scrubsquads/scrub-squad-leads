#!/usr/bin/env python3
"""Scrub Squad Contact Enrichment — Standalone Pipeline.

Reads leads from the Google Sheet "Leads" tab, searches for
decision-maker contacts via Apollo.io, enriches them, and writes
results to the "Contacts" tab.

Run manually:
    python tools/run_enrichment.py                     # default batch of 10
    python tools/run_enrichment.py --batch-size 50     # larger batch
    python tools/run_enrichment.py --dry-run            # search only, 0 credits
    python tools/run_enrichment.py --batch-size 541     # all leads

Required environment variables:
    APOLLO_API_KEY
    GOOGLE_SERVICE_ACCOUNT_JSON
    GOOGLE_SHEET_ID
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Load .env for local runs. GitHub Actions injects these as real env vars, so
# setdefault means CI values always win. Without this the script could only run
# inside Actions, which made local testing impossible.
# ---------------------------------------------------------------------------
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists() and not os.environ.get("GITHUB_ACTIONS"):
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _s = _line.strip()
        if _s and not _s.startswith("#") and "=" in _s:
            _k, _v = _s.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ---------------------------------------------------------------------------
# Path setup — allow importing sibling modules without a package __init__
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))

from apollo import (                                # noqa: E402
    enrich_person,
    extract_domain,
    normalize_contact,
    rank_contacts,
    search_people,
    INTER_ENRICH_DELAY,
    INTER_SEARCH_DELAY,
)
from sheets import (                                # noqa: E402
    CONTACTS_HEADERS,
    ENRICHMENT_LOG_HEADERS,
    append_contacts,
    get_client,
    get_or_create_worksheet,
    log_enrichment_run,
    read_existing_enriched_place_ids,
    read_leads_for_enrichment,
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


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Scrub Squad Contact Enrichment via Apollo.io",
    )
    parser.add_argument(
        "--batch-size", type=int, default=None,
        help="Max leads to enrich (default: from config, usually 10)",
    )
    parser.add_argument(
        "--max-contacts", type=int, default=None,
        help="Max contacts per company (default: from config, usually 2)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Search only — no enrichment credits spent",
    )
    parser.add_argument(
        "--business-type", default=None,
        help=("Only enrich leads whose business_type contains this string "
              "(case-insensitive), e.g. 'Property Management'. Credits are "
              "finite; this spends them on one segment instead of sheet order."),
    )
    parser.add_argument(
        "--max-credits", type=int, default=None,
        help="Hard stop once this many enrichment credits have been spent.",
    )
    parser.add_argument(
        "--no-filters", action="store_true",
        help=("Disable the bad-fit and out-of-market screens. By default both "
              "are ON, because a credit spent on a hospital system or a New "
              "York head office is a credit wasted."),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = _parse_args()
    start_time = datetime.now(timezone.utc)
    run_date = start_time.strftime("%Y-%m-%d")

    # --- Config -----------------------------------------------------------
    config = _load_config()
    apollo_cfg = config.get("apollo", {})

    batch_size = args.batch_size or apollo_cfg.get("default_batch_size", 10)
    max_contacts = args.max_contacts or apollo_cfg.get("max_contacts_per_company", 2)
    primary_titles = apollo_cfg.get("primary_titles", [])
    secondary_titles = apollo_cfg.get("secondary_titles", [])
    all_titles = primary_titles + secondary_titles
    seniorities = apollo_cfg.get("target_seniorities", [])
    small_threshold = apollo_cfg.get("small_company_threshold", 50)
    search_per_page = apollo_cfg.get("search_per_page", 10)

    logger.info("=" * 60)
    logger.info("Scrub Squad Contact Enrichment")
    logger.info("Run date: %s  |  Batch: %d  |  Max contacts/co: %d  |  Dry-run: %s",
                run_date, batch_size, max_contacts, args.dry_run)
    logger.info("=" * 60)

    # --- Env vars ---------------------------------------------------------
    apollo_key = os.environ.get("APOLLO_API_KEY")
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")

    if not all([apollo_key, sa_json, sheet_id]):
        logger.error(
            "Missing env vars. Required: APOLLO_API_KEY, "
            "GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID"
        )
        sys.exit(1)

    # --- Summary (written in finally block no matter what) ----------------
    summary = {
        "run_date":              run_date,
        "started_at":            start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at":           "",
        "duration_seconds":      "",
        "leads_processed":       0,
        "leads_skipped_no_data": 0,
        "contacts_found":        0,
        "contacts_enriched":     0,
        "credits_used":          0,
        "batch_size":            batch_size,
        "dry_run":               str(args.dry_run),
        "status":                "SUCCESS",
        "errors":                "",
        # Diagnostic counters. Not in ENRICHMENT_LOG_HEADERS, so they are
        # printed but not written to the sheet - log_enrichment_run() reads
        # by header name and ignores extras.
        "searched_by_domain":    0,
        "searched_by_name":      0,
    }

    enrichment_log_ws = None
    errors = []

    try:
        # --- Google Sheets connection -------------------------------------
        logger.info("Connecting to Google Sheets…")
        gc = get_client()
        spreadsheet = gc.open_by_key(sheet_id)
        leads_ws = get_or_create_worksheet(spreadsheet, "Leads", [])
        contacts_ws = get_or_create_worksheet(
            spreadsheet, "Contacts", CONTACTS_HEADERS,
        )
        enrichment_log_ws = get_or_create_worksheet(
            spreadsheet, "Enrichment_Log", ENRICHMENT_LOG_HEADERS,
        )

        # --- Read leads and existing enrichments --------------------------
        logger.info("Reading leads from Sheet…")
        all_leads = read_leads_for_enrichment(leads_ws)
        logger.info("Total leads in Sheet: %d", len(all_leads))

        logger.info("Reading already-enriched leads…")
        enriched_ids = read_existing_enriched_place_ids(contacts_ws)
        logger.info("Already enriched: %d leads", len(enriched_ids))

        # Filter to un-enriched leads, take batch_size
        leads_to_process = [
            lead for lead in all_leads
            if lead["place_id"].strip() not in enriched_ids
        ]
        logger.info("Un-enriched leads available: %d", len(leads_to_process))

        if not args.no_filters:
            # Reuse the curated blacklist rather than keeping a second copy.
            from close_classify_new_leads import classify as _classify

            # Copy promises South Florida service; a head office in another
            # state is not a buyer, and Apollo charges the same either way.
            SOUTH_FL = {"305", "786", "954", "561", "754"}

            def _area(p):
                d = "".join(c for c in str(p or "") if c.isdigit())
                if len(d) == 11 and d.startswith("1"):
                    d = d[1:]
                return d[:3] if len(d) == 10 else ""

            kept, dropped_bad, dropped_geo = [], [], []
            for l in leads_to_process:
                verdict, reason = _classify(l.get("business_name", ""))
                if verdict == "DEFINITE_BAD":
                    dropped_bad.append(f"{l.get('business_name')} [{reason}]")
                    continue
                ac = _area(l.get("phone"))
                if ac and ac not in SOUTH_FL:
                    dropped_geo.append(f"{l.get('business_name')} [{ac}]")
                    continue
                kept.append(l)
            logger.info("Credit screens: dropped %d bad-fit, %d out-of-market",
                        len(dropped_bad), len(dropped_geo))
            for d in dropped_bad[:5]:
                logger.info("    bad-fit:      %s", d)
            for d in dropped_geo[:5]:
                logger.info("    out-of-area:  %s", d)
            leads_to_process = kept

        if args.business_type:
            want = args.business_type.lower()
            before = len(leads_to_process)
            leads_to_process = [
                l for l in leads_to_process
                if want in l.get("business_type", "").lower()
            ]
            logger.info("Filtered to business_type ~ %r: %d of %d",
                        args.business_type, len(leads_to_process), before)

        # Prefer leads that actually have a domain - the name-only fallback
        # matches ~8% and burns the batch on leads that will not resolve.
        with_domain = [l for l in leads_to_process if l.get("website", "").strip()]
        without = [l for l in leads_to_process if not l.get("website", "").strip()]
        if with_domain:
            logger.info("Prioritising %d leads with a website over %d without",
                        len(with_domain), len(without))
            leads_to_process = with_domain + without

        leads_to_process = leads_to_process[:batch_size]
        logger.info("Processing this batch: %d leads", len(leads_to_process))

        if not leads_to_process:
            logger.info("Nothing to do — all leads already enriched.")

        # --- Process each lead --------------------------------------------
        for i, lead in enumerate(leads_to_process):
            place_id = lead["place_id"]
            biz_name = lead["business_name"]
            website = lead["website"]
            lead_phone = lead.get("phone", "")

            logger.info("-" * 50)
            logger.info("[%d/%d] %s", i + 1, len(leads_to_process), biz_name)

            try:
                # 1. Extract domain
                domain = extract_domain(website)
                if domain:
                    enrichment_source = "domain_search"
                    summary["searched_by_domain"] += 1
                    logger.info("  Domain: %s", domain)
                elif biz_name:
                    # Name search matches ~8% for small local businesses.
                    # Tracked separately so a run that is mostly name-fallback
                    # is visible instead of silently wasting the batch.
                    enrichment_source = "name_search"
                    summary["searched_by_name"] += 1
                    logger.info("  No domain — falling back to name: %s", biz_name)
                else:
                    logger.warning("  No domain and no business name — skipping")
                    summary["leads_skipped_no_data"] += 1
                    continue

                # 2. Search (FREE)
                raw_people = search_people(
                    api_key=apollo_key,
                    domain=domain,
                    company_name=biz_name if not domain else None,
                    titles=all_titles,
                    seniorities=seniorities,
                    per_page=search_per_page,
                )
                logger.info("  Search returned %d people", len(raw_people))

                if not raw_people:
                    logger.info("  No contacts found in Apollo — skipping")
                    summary["leads_processed"] += 1
                    continue

                # 3. Rank and pick best contacts
                best_people = rank_contacts(
                    raw_people, max_contacts, small_threshold,
                )
                summary["contacts_found"] += len(best_people)
                logger.info("  Selected %d contacts to enrich", len(best_people))

                if not best_people:
                    logger.info("  No relevant decision-makers found — skipping")
                    summary["leads_processed"] += 1
                    continue

                # Hard credit ceiling. Apollo's free tier is 100 credits per
                # billing cycle; without this a large batch silently drains it.
                if (args.max_credits is not None
                        and summary["credits_used"] >= args.max_credits):
                    logger.warning("  Credit ceiling reached (%d) — stopping early",
                                   args.max_credits)
                    break

                # 4. Enrich each contact (or skip in dry-run)
                contacts_for_lead = []
                for person in best_people:
                    person_title = person.get("title", "Unknown")
                    person_name = person.get("first_name", "?")

                    if args.dry_run:
                        logger.info("  [DRY-RUN] Would enrich: %s (%s)",
                                    person_name, person_title)
                        continue

                    logger.info("  Enriching: %s (%s) — 1 credit",
                                person_name, person_title)
                    person_id = person.get("id")
                    if not person_id:
                        logger.warning("  No Apollo ID — skipping person")
                        continue

                    enriched = enrich_person(apollo_key, person_id)
                    if not enriched:
                        logger.warning("  Enrichment returned empty — skipping")
                        continue

                    contact = normalize_contact(
                        enriched, place_id, biz_name,
                        enrichment_source, run_date,
                        fallback_phone=lead_phone,
                    )
                    contacts_for_lead.append(contact)
                    summary["contacts_enriched"] += 1
                    summary["credits_used"] += 1

                    # Rate-limit delay between enrichment calls
                    time.sleep(INTER_ENRICH_DELAY)

                # 5. Write contacts to Sheet (per-lead batch)
                if contacts_for_lead:
                    append_contacts(contacts_ws, contacts_for_lead)
                    logger.info("  Written %d contacts to Contacts tab",
                                len(contacts_for_lead))

                summary["leads_processed"] += 1

            except Exception as exc:
                # Credit exhaustion — stop early
                if hasattr(exc, "response") and \
                   getattr(exc.response, "status_code", 0) == 402:
                    msg = "Apollo credits exhausted — stopping early"
                    logger.error(msg)
                    errors.append(msg)
                    summary["status"] = "PARTIAL_FAILURE"
                    break

                msg = f"Lead '{biz_name}' failed: {exc}"
                logger.error("  %s", msg, exc_info=True)
                errors.append(msg)
                summary["leads_processed"] += 1
                continue

            # Brief pause between leads (search calls)
            if i < len(leads_to_process) - 1:
                time.sleep(INTER_SEARCH_DELAY)

    except Exception as exc:
        summary["status"] = "FAILED"
        errors.append(str(exc))
        logger.error("Pipeline failed: %s", exc, exc_info=True)

    finally:
        # --- Always write run summary ------------------------------------
        end_time = datetime.now(timezone.utc)
        summary["finished_at"] = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        summary["duration_seconds"] = round(
            (end_time - start_time).total_seconds(), 1,
        )
        if errors and summary["status"] == "SUCCESS":
            summary["status"] = "PARTIAL_FAILURE"

        # A run that processed a real batch and found NOTHING is a failure,
        # not a success. Without this, 12 consecutive days of zero-yield runs
        # logged SUCCESS and nobody noticed the pipeline had stopped producing.
        #
        # Threshold matters: a handful of leads legitimately returning nothing
        # is ordinary variance, so only a batch of decent size counts as
        # evidence that something is actually broken.
        BARREN_BATCH_THRESHOLD = 10
        if (summary["status"] == "SUCCESS"
                and summary["leads_processed"] >= BARREN_BATCH_THRESHOLD
                and summary["contacts_found"] == 0):
            summary["status"] = "NO_RESULTS"
            errors.append(
                f"Processed {summary['leads_processed']} leads and found 0 "
                f"contacts. Domain searches: {summary['searched_by_domain']}, "
                f"name-only fallbacks: {summary['searched_by_name']}. "
                "A fully barren batch usually means missing domains or a "
                "rejected API key, not an empty market."
            )

        summary["errors"] = " | ".join(errors)

        if enrichment_log_ws is not None:
            try:
                log_enrichment_run(enrichment_log_ws, summary)
            except Exception as log_exc:
                logger.error("Failed to write Enrichment_Log: %s", log_exc)

        # --- Print summary -----------------------------------------------
        logger.info("=" * 60)
        logger.info("Enrichment Summary")
        logger.info("  Status:              %s", summary["status"])
        logger.info("  Leads processed:     %d", summary["leads_processed"])
        logger.info("  Leads skipped:       %d", summary["leads_skipped_no_data"])
        logger.info("  Searched by domain:  %d", summary["searched_by_domain"])
        logger.info("  Searched by name:    %d  (weak path, ~8%% match rate)",
                    summary["searched_by_name"])
        logger.info("  Contacts found:      %d", summary["contacts_found"])
        logger.info("  Contacts enriched:   %d", summary["contacts_enriched"])
        logger.info("  Credits used:        %d", summary["credits_used"])
        logger.info("  Duration:            %ss", summary["duration_seconds"])
        if summary["dry_run"] == "True":
            logger.info("  ** DRY-RUN — no credits were spent **")
        if errors:
            logger.info("  Errors:              %s", summary["errors"])
        logger.info("=" * 60)

    # Non-zero exit on any failure
    if summary["status"] not in ("SUCCESS",):
        sys.exit(1)


if __name__ == "__main__":
    main()
