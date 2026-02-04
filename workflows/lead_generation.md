# Scrub Squad Lead Generator — Daily Ops Reference

Use this document after setup is complete.  It covers what happens
every day, how to check results, how to add regions or business types,
and how to handle common problems.

---

## What happens every day

At **8:00 AM ET** (9:00 AM during daylight saving time), GitHub Actions
runs the pipeline automatically.  Here is what it does, in order:

1. Reads `configs/queries.yaml` to know which business types and regions to search.
2. Calls Outscraper for each combination (12 queries by default).
3. Reads the existing "Leads" tab to find which businesses have already been added.
4. Filters out duplicates — only truly new businesses pass through.
5. Appends the new leads to the "Leads" tab with timestamps.
6. Writes a one-line summary to the "Run_Log" tab.

---

## How to check results

### Quick check (daily)
Open your Google Sheet.

- **Leads tab** — new rows appear at the bottom each day.  Each row
  includes a clickable Google Maps link in the `google_maps_link` column.
- **Run_Log tab** — one new row per run.  Key columns:
  - `status` — `SUCCESS` or `PARTIAL_FAILURE`
  - `new_appended` — how many leads were added today
  - `dupes_skipped` — how many were already in the Sheet

### If you missed a notification
Go to your GitHub repo → **Actions** tab.  Each run is listed with a
green (success) or red (failure) icon.  Click into any run to see the
full log output.

---

## How to add a new region

1. Open `configs/queries.yaml` in the repo.
2. Add one line under `regions:`:
   ```yaml
   regions:
     - "Miami-Dade County, FL, USA"
     - "Homestead, FL, USA"
     - "Key Largo, FL, USA"
     - "Broward County, FL, USA"
     - "Your New Region, STATE, USA"   # <-- add here
   ```
3. Commit and push.  The next run picks it up automatically.

The format should be: **City or County name, State abbreviation, USA**.
This is what Outscraper uses to locate results on Google Maps.

---

## How to add a new business type

Same as adding a region, but under `business_types:`:

```yaml
business_types:
  - "Property Management Companies"
  - "Medical Offices"
  - "Construction Companies"
  - "Janitorial Services"   # <-- add here
```

Use the phrasing you would type into Google Maps search.  The pipeline
plugs it directly into a search query.

---

## How to change results per query

Edit `configs/queries.yaml` → change `results_per_query` under `settings`:

```yaml
settings:
  results_per_query: 20    # increase or decrease here
  language: "en"
```

More results per query = more Outscraper credits consumed per day.
Check your Outscraper plan limits before increasing this.

---

## Common problems and fixes

### "No new leads" every day
After the first 1–2 weeks the target regions will saturate — most
businesses have already been pulled.  This is normal.  New leads will
trickle in as businesses open or change.  If you want more leads,
add new regions or business types.

### GitHub Actions job turns red
1. Go to Actions → click the failed run → read the log.
2. Most common causes:
   - **403 Forbidden** — the service account lost access to the Sheet.
     Re-share it (see Setup Guide Step 6).
   - **Outscraper API error** — your Outscraper plan may have hit its
     credit limit.  Check your Outscraper dashboard.
   - **Missing env var** — a secret was deleted or misspelled in GitHub.
     Re-check repo Settings → Secrets.

### The run says PARTIAL_FAILURE
Some queries succeeded, others did not.  The leads from successful
queries were still added.  Check the `errors` column in the Run_Log
tab for details.  Usually caused by a temporary Outscraper outage —
the next day's run will retry automatically.

### I see duplicate tab names ("Leads" and "Leads")
This happens if someone renamed the original "Leads" tab manually.
The pipeline couldn't find it, so it created a new one.  To fix:
1. Delete the empty duplicate tab.
2. Rename the tab with your data back to exactly **Leads** (capital L).

> **Important:** Never rename the "Leads" or "Run_Log" tabs.  The
> pipeline matches tab names exactly — "leads" or "LEADS" will not work.

---

## How to run it manually

Go to your GitHub repo → **Actions** → **Scrub Squad Daily Leads** →
**Run workflow** → click the green button.  Useful for testing after
making changes or recovering from a failure.

---

## What the columns mean (Leads tab)

| Column | What it is |
|---|---|
| place_id | Google Maps unique ID.  Used internally to prevent duplicates — do not edit. |
| business_name | The business name as it appears on Google Maps |
| business_type | Which search category surfaced this lead |
| region | Which target region was searched |
| full_address | Full street address |
| phone | Phone number (usually present) |
| email | Email address (often blank — Google Maps rarely includes these) |
| website | Website URL |
| rating | Google Maps rating (0–5) |
| reviews_count | Number of Google reviews |
| google_maps_link | Click to open the business on Google Maps |
| query_used | The exact search that found this lead (for debugging) |
| pulled_at | Exact timestamp when the lead was scraped |
| run_date | Which day's pipeline run added this lead |

---

## Timing note (DST)

The pipeline runs at **13:00 UTC** every day.
- **November – March (EST):** that is 8:00 AM Eastern.
- **March – November (EDT):** that is 9:00 AM Eastern.

This 1-hour seasonal shift is a limitation of GitHub Actions scheduling.
It does not affect lead quality or completeness.
