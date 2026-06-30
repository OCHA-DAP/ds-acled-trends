import logging

import ocha_stratus as stratus

from src.constants import (
    ALL_BASENAME,
    DEFAULT_COMPARISON_LAG,
    DEFAULT_OUTCOME,
    LATEST_BASENAME,
    PROCESSED_PREFIX,
    dated_basename,
)
from src.scraper import build_all_table, get_trends_table

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def main() -> None:
    df = get_trends_table(outcome=DEFAULT_OUTCOME, lag=DEFAULT_COMPARISON_LAG)
    period_end = df["period_end"].iloc[0].isoformat()

    # Upload this run's measured period as its dated file and as "latest".
    for basename in (dated_basename(period_end), LATEST_BASENAME):
        blob_name = f"{PROCESSED_PREFIX}/{basename}"
        logger.info("Uploading to blob: %s", blob_name)
        stratus.upload_csv_to_blob(df, blob_name, stage="dev")

    # Rebuild the cumulative "all" file from every per-date file in blob
    # (includes the one just uploaded) and upload it.
    all_df = build_all_table()
    all_blob = f"{PROCESSED_PREFIX}/{ALL_BASENAME}"
    logger.info("Uploading to blob: %s (%d rows)", all_blob, len(all_df))
    stratus.upload_csv_to_blob(all_df, all_blob, stage="dev")

    logger.info("Done — %d countries this period, %d rows in 'all'", len(df), len(all_df))


if __name__ == "__main__":
    main()
