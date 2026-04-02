import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Setup logging before importing pipeline modules
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

import config

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(module)s | %(message)s",
    handlers=[
        logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)),
        logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

from pipeline import db, aggregator, filter as filter_layer, analyzer, assembler, delivery


def run(run_date: str, dry_run: bool = False) -> None:
    logger.info(f"=== AI Pulse starting for {run_date} (dry_run={dry_run}) ===")

    # Initialize DBs
    try:
        db.init_seen_items_db()
        db.init_feedback_db()
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}", exc_info=True)
        sys.exit(1)

    # Layer 1 — Aggregate
    seen_ids = db.get_seen_ids()
    new_items = aggregator.aggregate(seen_ids)
    logger.info(f"Layer 1 complete: {len(new_items)} new items")

    if not new_items:
        logger.info("No new items found. Exiting.")
        return

    # Layer 2 — Filter
    passing_items, relevance_scores, filter_meta = filter_layer.filter_items(new_items)
    logger.info(f"Layer 2 complete: {len(passing_items)} items passed filter")

    # Record all new items in seen_items DB
    included_ids = {item.id for item in passing_items}
    db.insert_seen_items(new_items, relevance_scores=relevance_scores, included_ids=included_ids)

    if not passing_items:
        logger.info("No items passed relevance filter. Saving empty briefing.")
        briefing = assembler.assemble([], run_date, total_reviewed=len(new_items))
        delivery.send_email(briefing, dry_run=dry_run)
        return

    # Layer 3 — Analyze
    enriched_items = analyzer.analyze_items(passing_items, relevance_scores, filter_meta)
    logger.info(f"Layer 3 complete: {len(enriched_items)} items enriched")

    # Layer 4 — Assemble
    briefing = assembler.assemble(enriched_items, run_date, total_reviewed=len(new_items))
    logger.info("Layer 4 complete: briefing assembled")

    # Layer 5 — Deliver
    delivery.send_email(briefing, dry_run=dry_run)
    logger.info("Layer 5 complete: delivery done")

    logger.info(f"=== AI Pulse complete: {briefing['total_items_included']} items in briefing ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Pulse — Daily AI Briefing Pipeline")
    parser.add_argument("--date", default=None, help="Run for specific date YYYY-MM-DD (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Run full pipeline but skip email send")
    args = parser.parse_args()

    run_date = args.date or datetime.now(timezone.utc).date().isoformat()

    try:
        run(run_date, dry_run=args.dry_run)
    except Exception as e:
        logger.critical(f"Unhandled exception in main: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
