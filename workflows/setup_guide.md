# Scrub Squad Lead Generator — One-Time Setup Guide

Run these steps once before the first automated run.  You do not need
to be a developer — every step includes exactly what to click.

---

## What you need before you start

| Item | Where to get it |
|---|---|
| A Google account | Any Google account works |
| An Outscraper account | [outscraper.com](https://outscraper.com) — free tier exists but a paid plan is needed for daily operation (see note below) |
| A GitHub account | [github.com](https://github.com) — the repo must already be pushed here |

> **Outscraper credits:** The free plan allows 500 business records per
> month.  This pipeline can pull up to 240 records per day, so the free
> tier runs out in 2–3 days.  Upgrade to a paid plan before going live.

---

## Step 1 — Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Click **Create project** (top-left dropdown).
3. Give it any name (e.g., "Scrub Squad Leads").
4. Click **Create**.  Wait for the project to finish creating.

---

## Step 2 — Enable the Google Sheets API

1. In Google Cloud Console, click the **hamburger menu** (three lines, top-left).
2. Click **APIs & Services** → **Library**.
3. Search for **Sheets API**.
4. Click the result → click **Enable**.

---

## Step 3 — Create a service account

A service account is a robot user that the pipeline logs in as.

1. Still in Google Cloud Console: **APIs & Services** → **Credentials**.
2. Click **Create credentials** (top) → **Service account**.
3. Fill in:
   - **Service account name:** `scrub-squad-leads`  (any name is fine)
   - **Service account ID:** leave the auto-generated value
   - **Description:** optional
4. Click **Create and continue**.
5. **Role:** click the dropdown → search for **Editor** → select it.
6. Click **Continue** → **Done**.

---

## Step 4 — Download the service account key

1. You should now see the service account listed.  Click on its name.
2. Click the **Keys** tab.
3. Click **Add key** → **Create new key** → keep **JSON** selected → click **Create**.
4. A `.json` file downloads automatically.  **Keep this file safe — it is a secret.**  Do not share it or commit it to git.

---

## Step 5 — Create your Google Sheet

1. Go to [sheets.google.com](https://sheets.google.com).
2. Click **Create** → **Blank spreadsheet**.
3. Leave everything as-is.  The pipeline will automatically create
   the "Leads" and "Run_Log" tabs with the correct headers on the first run.
4. **Grab the Sheet ID** from the URL.  It is the long alphanumeric string
   between `/spreadsheets/d/` and `/edit`.

   Example URL:
   ```
   https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit
                                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                            This is your Sheet ID
   ```

---

## Step 6 — Share the Sheet with the service account

The pipeline needs write access to the Sheet.

1. Open your Sheet → click **Share** (top-right).
2. Open the `.json` key file you downloaded in Step 4.  Find the
   `"client_email"` value.  It looks like:
   ```
   scrub-squad-leads@scrub-squad-leads-XXXXX.iam.gserviceaccount.com
   ```
3. Paste that email into the Share dialog.
4. Set the role to **Editor**.
5. Click **Send**.

---

## Step 7 — Get your Outscraper API key

1. Log in at [outscraper.com](https://outscraper.com).
2. Go to your dashboard → **API Keys** (or Settings → API).
3. Copy your API key.

---

## Step 8 — Add secrets to GitHub

GitHub Actions reads secrets from the repo settings — not from files.

1. Go to your GitHub repo.
2. Click **Settings** → **Secrets and variables** → **Actions**.
3. Click **New repository secret** and add each one:

| Secret name | Value |
|---|---|
| `OUTSCRAPER_API_KEY` | Your Outscraper API key from Step 7 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Open the `.json` file from Step 4 in a text editor.  Select **all** the text and paste it here.  Keep it as-is — do not modify it. |
| `GOOGLE_SHEET_ID` | The Sheet ID you copied in Step 5 |

---

## Step 9 — Push the code and do a test run

1. Make sure all project files are committed and pushed to your GitHub repo.
2. Go to the repo → **Actions** tab.
3. Click **Scrub Squad Daily Leads** in the left sidebar.
4. Click **Run workflow** → select the default branch → click **Run workflow**.
5. Wait for the job to finish (usually under a minute).
6. If it turns green: open your Google Sheet.  You should see leads in the
   "Leads" tab and one row in the "Run_Log" tab.
7. If it turns red: click into the job → look at the log output.  The most
   common issue is the service account not being shared with the Sheet
   (Step 6).

---

## You are done

The pipeline will now run automatically every day at 8 AM ET (9 AM during
daylight saving time).  See `workflows/lead_generation.md` for how to
monitor it and make changes going forward.
