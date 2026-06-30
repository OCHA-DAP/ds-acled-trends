import logging

import ocha_stratus as stratus

from src.constants import DEFAULT_COMPARISON_LAG, DEFAULT_OUTCOME, PROJECT_PREFIX
from src.scraper import get_trends_table

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def main() -> None:
    df = get_trends_table(outcome=DEFAULT_OUTCOME, lag=DEFAULT_COMPARISON_LAG)
    period_end = df["period_end"].iloc[0].isoformat()

    dated_blob = (
        f"{PROJECT_PREFIX}/processed/acled/"
        f"trends_{DEFAULT_OUTCOME}_{period_end}.csv"
    )
    latest_blob = (
        f"{PROJECT_PREFIX}/processed/acled/trends_{DEFAULT_OUTCOME}_latest.csv"
    )

    for blob_name in (dated_blob, latest_blob):
        logger.info("Uploading to blob: %s", blob_name)
        stratus.upload_csv_to_blob(df, blob_name, stage="dev")

    logger.info("Done — %d countries written", len(df))


if __name__ == "__main__":
    main()
