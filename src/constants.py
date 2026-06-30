PROJECT_PREFIX = "ds-acled-trends"

# The ACLED Trends ("trendfinder") app reads its data from this public API.
# No authentication is required — the browser sends only a Referer header.
TRENDS_API_BASE = "https://trendfinder-api.acledapps.com/api/v1"
OVERVIEW_URL = f"{TRENDS_API_BASE}/overview"
REFERER = "https://apps.acleddata.com/"

# Conflict type shown in the "Conflict type" dropdown.
DEFAULT_OUTCOME = "organized_violence"

# `lead` selects the 4-week period: 0 is the most recent *completed* period
# (labelled "measured" in the app), 1-6 are the predicted future periods.
MEASURED_LEAD = 0

# `lag` is the comparison baseline ("Compare to avg. of previous"):
# 1 = Month, 6 = 6 Months, 12 = Year. The app defaults to Year.
DEFAULT_COMPARISON_LAG = 12

# Blob storage layout. The per-date, latest, and cumulative "all" CSVs all live
# under this prefix in the dev "projects" container.
PROCESSED_PREFIX = f"{PROJECT_PREFIX}/processed/acled"


def dated_basename(period_end: str) -> str:
    return f"trends_{DEFAULT_OUTCOME}_{period_end}.csv"


LATEST_BASENAME = f"trends_{DEFAULT_OUTCOME}_latest.csv"
ALL_BASENAME = f"trends_{DEFAULT_OUTCOME}_all.csv"
