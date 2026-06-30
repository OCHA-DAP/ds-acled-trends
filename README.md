# ds-acled-trends

Scrapes the current-period organized violence figures from the
[ACLED Trends](https://acleddata.com/platform/trends) platform and stores them
as a tidy table in Azure blob storage.

## How it works

The Trends page is a client-side app ("trendfinder") that reads its data from a
**public** JSON API — no login is required:

```
https://trendfinder-api.acledapps.com/api/v1/overview?outcome=organized_violence&lead=0&lag=12
```

- `outcome` — conflict type (`organized_violence` by default).
- `lead` — which 4-week period: `0` is the most recent *completed* period
  (labelled **"measured"** in the app), `1`–`6` are the predicted future periods.
- `lag` — comparison baseline ("Compare to avg. of previous"): `1` = Month,
  `6` = 6 Months, `12` = Year (the app default).

The pipeline fetches the **measured** period (`lead=0`) for organized violence,
parses `displayData.countries` into one row per country, and uploads two CSV
files to blob storage:

- `ds-acled-trends/processed/acled/trends_organized_violence_<period_end>.csv`
- `ds-acled-trends/processed/acled/trends_organized_violence_latest.csv`

### Output columns

| Column | Description |
|---|---|
| `country` | Country / territory name |
| `country_id` | UN M49 numeric code (as string) |
| `region` | ACLED region |
| `lat`, `lng` | Centroid coordinates |
| `event_count` | Organized violence events in the measured period |
| `change_pct` | Fractional change vs. comparison avg (e.g. `-0.39` = −39%) |
| `change_abs` | Absolute change vs. comparison avg |
| `outcome` | Conflict type (`organized_violence`) |
| `period_start`, `period_end` | Measured 4-week period bounds |
| `comparison` | Comparison baseline label (e.g. `Year`) |
| `comparison_start`, `comparison_end` | Comparison window bounds |
| `latest_update` | ACLED data update date |

## Running locally

No ACLED credentials are needed — only a blob write SAS token:

```bash
DSCI_AZ_BLOB_DEV_SAS_WRITE=... \
uv run python pipelines/run_scrape.py
```

Runs every Monday at 10:00 UTC via GitHub Actions, or can be triggered manually.

## Secrets

| Secret | Description |
|---|---|
| `DSCI_AZ_BLOB_DEV_SAS_WRITE` | Azure blob write SAS token |
