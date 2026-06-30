import io
import logging
import re
from datetime import date, datetime, timezone

import ocha_stratus as stratus
import pandas as pd
import requests

from src.constants import (
    DEFAULT_COMPARISON_LAG,
    DEFAULT_OUTCOME,
    MEASURED_LEAD,
    OVERVIEW_URL,
    PROCESSED_PREFIX,
    REFERER,
)

logger = logging.getLogger(__name__)

# Matches the per-date CSV blobs, e.g. trends_organized_violence_2026-06-19.csv
_DATED_RE = re.compile(
    rf"{re.escape(PROCESSED_PREFIX)}/trends_{re.escape(DEFAULT_OUTCOME)}_"
    r"(\d{4}-\d{2}-\d{2})\.csv$"
)

# Columns that uniquely identify a country's row within one period.
_DEDUP_KEYS = ["outcome", "period_start", "period_end", "country_id"]


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


def _write_container_client():
    """Container client built with the write SAS token.

    The write token carries read+list permissions, so it is used for reads too
    — the separate read token is not provisioned in CI.
    """
    return stratus.get_container_client(stage="dev", write=True)


def list_dated_blobs() -> list[str]:
    """List all per-date CSV blobs for the configured outcome, sorted by date."""
    cc = _write_container_client()
    prefix = f"{PROCESSED_PREFIX}/trends_{DEFAULT_OUTCOME}_"
    names = [b.name for b in cc.list_blobs(name_starts_with=prefix)]
    return sorted(n for n in names if _DATED_RE.search(n))


def _read_csv_blob(cc, blob_name: str) -> pd.DataFrame:
    data = cc.get_blob_client(blob_name).download_blob().readall()
    return pd.read_csv(io.BytesIO(data))


def build_all_table() -> pd.DataFrame:
    """Build the cumulative table from every per-date CSV currently in blob.

    Rebuilt from scratch each run (self-healing), deduplicated to one row per
    country per measured period, and sorted by period then event count.
    """
    cc = _write_container_client()
    names = list_dated_blobs()
    frames = [_read_csv_blob(cc, n) for n in names]
    if not frames:
        logger.warning("No per-date CSVs found in blob; 'all' table is empty")
        return pd.DataFrame()
    all_df = pd.concat(frames, ignore_index=True)
    before = len(all_df)
    all_df = all_df.drop_duplicates(subset=_DEDUP_KEYS, keep="last")
    all_df = all_df.sort_values(
        ["period_end", "event_count"], ascending=[True, False]
    ).reset_index(drop=True)
    logger.info(
        "Built 'all' table from %d per-date files: %d rows (%d dropped as dups)",
        len(names),
        len(all_df),
        before - len(all_df),
    )
    return all_df
