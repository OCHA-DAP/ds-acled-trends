import logging
from datetime import date, datetime, timezone

import pandas as pd
import requests

from src.constants import (
    DEFAULT_COMPARISON_LAG,
    DEFAULT_OUTCOME,
    MEASURED_LEAD,
    OVERVIEW_URL,
    REFERER,
)

logger = logging.getLogger(__name__)


def _to_date(ts: int | None) -> date | None:
    """Convert a Unix timestamp (seconds, UTC) to a date, or None if missing."""
    if ts in (None, "", 0):
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()


def _to_float(value) -> float | None:
    """Coerce API numbers to float; the API uses '' for missing values."""
    if value is None or value == "":
        return None
    return float(value)


def fetch_overview(
    outcome: str = DEFAULT_OUTCOME,
    lead: int = MEASURED_LEAD,
    lag: int = DEFAULT_COMPARISON_LAG,
) -> dict:
    """Fetch the raw ACLED Trends overview payload for one period/comparison."""
    params = {"outcome": outcome, "lead": lead, "lag": lag}
    logger.info("Fetching ACLED Trends overview: %s", params)
    r = requests.get(
        OVERVIEW_URL, params=params, headers={"Referer": REFERER}, timeout=60
    )
    r.raise_for_status()
    return r.json()


def parse_measured_table(
    payload: dict,
    outcome: str = DEFAULT_OUTCOME,
    lag: int = DEFAULT_COMPARISON_LAG,
) -> pd.DataFrame:
    """Parse the overview payload into a tidy per-country table for the
    measured (most recent completed) 4-week period.

    One row per country with the event count and the change vs. the
    comparison baseline. Scenario columns (best/worst case) do not apply to
    the measured period and are omitted.
    """
    time_ranges = payload["filters"]["filterTimeRanges"]
    measured = next((r for r in time_ranges if r.get("type") == "measured"), None)
    if measured is None:
        raise RuntimeError("No 'measured' period found in filterTimeRanges")
    period_start = _to_date(measured["start"])
    period_end = _to_date(measured["end"])

    comparison_ranges = payload["filters"]["filterComparisonTimeRanges"]
    comparison_label = next(
        (c["name"] for c in comparison_ranges if str(c["id"]) == str(lag)), str(lag)
    )

    meta = payload.get("metadata", {})
    comparison_start = _to_date(meta.get("comparisonStart"))
    comparison_end = _to_date(meta.get("comparisonEnd"))
    latest_update = _to_date(meta.get("latestUpdate"))

    countries = payload["displayData"]["countries"]
    rows = [
        {
            "country": c["name"],
            "country_id": c["id"],
            "region": c.get("region"),
            "lat": _to_float(c.get("lat")),
            "lng": _to_float(c.get("lng")),
            "event_count": _to_float(c.get("value")),
            "change_pct": _to_float(c.get("change_pct")),
            "change_abs": _to_float(c.get("change_abs")),
        }
        for c in countries
    ]
    df = pd.DataFrame(rows)
    # Event counts are integers; keep nullable to tolerate any missing values.
    df["event_count"] = df["event_count"].round().astype("Int64")
    df["outcome"] = outcome
    df["period_start"] = period_start
    df["period_end"] = period_end
    df["comparison"] = comparison_label
    df["comparison_start"] = comparison_start
    df["comparison_end"] = comparison_end
    df["latest_update"] = latest_update

    df = df.sort_values(
        "event_count", ascending=False, na_position="last"
    ).reset_index(drop=True)
    logger.info(
        "Parsed %d countries for measured period %s -> %s",
        len(df),
        period_start,
        period_end,
    )
    return df


def get_trends_table(
    outcome: str = DEFAULT_OUTCOME,
    lag: int = DEFAULT_COMPARISON_LAG,
) -> pd.DataFrame:
    """Fetch and parse the measured-period organized violence table."""
    payload = fetch_overview(outcome=outcome, lead=MEASURED_LEAD, lag=lag)
    return parse_measured_table(payload, outcome=outcome, lag=lag)
