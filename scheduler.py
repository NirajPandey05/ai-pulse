import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import schedule
import time

import config

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(module)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def run_pipeline() -> None:
    from main import run
    run_date = datetime.now(timezone.utc).date().isoformat()
    logger.info(f"Scheduler: triggering pipeline for {run_date}")
    try:
        run(run_date)
    except Exception as e:
        logger.error(f"Scheduler: pipeline failed — {e}", exc_info=True)


def health_check() -> None:
    logger.info(f"Scheduler health check — {datetime.now(timezone.utc).isoformat()}")


schedule.every().day.at(config.BRIEFING_SEND_TIME).do(run_pipeline)
schedule.every().day.at(config.BRIEFING_SEND_TIME).do(health_check)

logger.info(f"Scheduler started — pipeline runs daily at {config.BRIEFING_SEND_TIME}")

while True:
    schedule.run_pending()
    time.sleep(60)
