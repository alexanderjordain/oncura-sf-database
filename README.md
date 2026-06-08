# Oncura — Salesforce Lookup (SF Database)

Internal Salesforce-style reference for Oncura's frozen SF snapshot (taken
2026-03-25; SF was deactivated 2026-06-01). Lets sales reps look up any clinic
— overview, contacts, opportunities, activities, history — without needing live
SF access.

## Stack

- **Streamlit** UI (single-file `app.py`)
- **SQLite** read-only DB shipped as a GitHub Release asset (~270 MB), fetched
  on first cold-start and cached for the container's lifetime
- Hosted on **Streamlit Community Cloud**

## Pages

- **Clinic search** — Salesforce-style list of matches, click anywhere on a row
  to open the detail
- **Clinic detail** — highlights panel + tabbed Contacts (cards) ·
  Opportunities (with stage badges) · Activities (timeline) · Events · Cases ·
  History · Files
- **Sales activity** — closed-won by year + top clinics
- **Renewal radar** — partner clinics ranked by install age

## Deploy

1. Repo on GitHub, branch `main`, file `app.py`.
2. The SQLite database is **not** committed (it's >100 MB). Upload
   `oncura_sf_lookup_lite.db` to a GitHub Release on this repo with the tag
   `snapshot-2026-03-25` — `app.py` will download it on first run.
3. On [share.streamlit.io](https://share.streamlit.io), create a new app
   pointing at this repo + branch + `app.py`.
4. (Optional) override `ONCURA_DB_URL` in Streamlit Cloud secrets if you host
   the DB elsewhere.

## Local dev

```bash
pip install -r requirements.txt
# Point at the local DB instead of downloading
$env:ONCURA_DB_PATH = "C:\path\to\oncura_sf_lookup_lite.db"
streamlit run app.py
```

## Refreshing the data

The data is a frozen snapshot — no scheduled refresh. If you ever rebuild it,
re-run `trim_db_for_cloud.py` against an updated source DB and upload the new
file as a new GitHub Release (then bump `ONCURA_DB_URL` if the URL changes).
