# Scrub Squad Contact Enrichment — Ops Reference

This pipeline finds decision-makers at leads already in your Google Sheet
using Apollo.io, and writes their name, title, email, and phone to a
separate "Contacts" tab.

---

## How to run it

### Dry-run (free, 0 credits — test the flow first)
```bash
python tools/run_enrichment.py --dry-run
```
Searches Apollo for contacts but does NOT reveal emails/phones.
Check the terminal output to see what it would find.

### Small test batch (2-4 credits)
```bash
python tools/run_enrichment.py --batch-size 2
```
Enriches 2 companies with up to 2 contacts each.

### Full run — all 541 leads (~1,000 credits)
```bash
python tools/run_enrichment.py --batch-size 600
```
Processes all un-enriched leads.  Can be re-run safely — already-enriched
companies are skipped automatically.

### Custom contacts per company
```bash
python tools/run_enrichment.py --batch-size 50 --max-contacts 1
```
Only gets 1 contact per company instead of the default 2.

---

## Required environment variables

| Variable | Where to get it |
|---|---|
| `APOLLO_API_KEY` | Apollo.io → Settings → Integrations → API → API Keys |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Same as lead pipeline (already set) |
| `GOOGLE_SHEET_ID` | Same as lead pipeline (already set) |

All three must be set in `.env` (for local runs) or in GitHub Secrets
(for future automated runs).

---

## What it does, step by step

1. Reads all leads from the "Leads" tab (place_id, business_name, website).
2. Reads the "Contacts" tab to see which companies already have contacts.
3. Skips already-enriched companies.
4. For each un-enriched lead:
   - Extracts the domain from the website URL (or falls back to company name).
   - Searches Apollo for people with cleaning-relevant titles (FREE).
   - Ranks contacts: facility/operations titles first, executives only at small companies.
   - Enriches the top 1-2 contacts to reveal email and phone (1 credit each).
   - Writes contact rows to the "Contacts" tab immediately.
5. Logs a run summary to the "Enrichment_Log" tab.

---

## How to check results

### Contacts tab
Each row is one decision-maker.  A company with 2 contacts gets 2 rows.

| Column | What it is |
|---|---|
| place_id | Links back to the Leads tab (same business) |
| business_name | Company name (for easy reading) |
| apollo_person_id | Apollo's unique ID — used to prevent duplicate contacts |
| first_name | Contact's first name |
| last_name | Contact's last name |
| title | Job title (e.g., "Facility Manager") |
| email | Email address |
| email_status | "verified", "guessed", or blank |
| phone | Phone number (if available) |
| linkedin_url | LinkedIn profile URL |
| seniority | Apollo's seniority classification |
| enrichment_source | "domain_search" or "name_search" (domain is higher confidence) |
| enriched_at | When this contact was enriched (UTC) |
| run_date | Which enrichment run added this contact |

### Enrichment_Log tab
One row per run with: leads processed, contacts found, credits used, status.

---

## Who it searches for

The pipeline targets people who make cleaning service decisions:

**Primary (always searched):**
- Facility Manager / Director of Facilities
- Office Manager
- Operations Manager / Director of Operations
- Building Manager / Property Manager
- Maintenance Manager

**Secondary (only at small companies with <50 employees):**
- Owner / CEO / President

This means at a large property management firm you'll get the Facility
Manager, not the CEO.  At a 10-person medical office, you'll get the
Owner who handles everything.

These titles are configurable in `configs/queries.yaml` under the
`apollo:` section.

---

## Credit usage

| Action | Cost |
|---|---|
| People Search (finding contacts) | FREE |
| People Enrich (revealing email/phone) | 1 credit per person |
| Dry-run mode | 0 credits |

With the Basic plan (2,500 credits/month), you can enrich all 541
existing leads plus new daily leads with room to spare.

---

## Common problems and fixes

### "Apollo credits exhausted"
The pipeline stops early and saves everything it has so far.  Check your
Apollo dashboard for credit usage.  Runs can be safely re-started — it
picks up where it left off.

### Low hit rate (many companies with 0 contacts)
Small local businesses often aren't in Apollo's database.  This is
normal.  The pipeline automatically falls back to company name search
when no website domain is available, but some businesses simply won't
have contacts in Apollo.

### "No domain — falling back to name"
The lead doesn't have a website URL, so Apollo searches by company name
(fuzzy match).  Results may be less precise.  This is expected for
businesses without websites.

### Running it again duplicates nothing
The pipeline checks the "Contacts" tab before enriching.  Companies
that already have contacts are skipped.  Safe to run multiple times.

---

## Configuring search targets

Edit `configs/queries.yaml` → `apollo:` section:

```yaml
apollo:
  primary_titles:
    - "Facility Manager"
    - "Your New Title Here"    # add here
  secondary_titles:
    - "Owner"
  small_company_threshold: 50  # employees
  max_contacts_per_company: 2
  default_batch_size: 10
```

---

## Future: adding to the daily pipeline

When you're ready to automate enrichment daily (after confirming hit
rate is good), add `APOLLO_API_KEY` to GitHub Secrets and a second job
to `.github/workflows/scrub_squad.yml` that runs after the scrape job.
