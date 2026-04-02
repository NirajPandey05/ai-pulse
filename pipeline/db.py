import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
SEEN_ITEMS_DB = DATA_DIR / "seen_items.db"
FEEDBACK_DB = DATA_DIR / "feedback.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_seen_items_db() -> None:
    conn = _connect(SEEN_ITEMS_DB)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_items (
                id TEXT PRIMARY KEY,
                title TEXT,
                source TEXT,
                seen_at TEXT,
                relevance_score REAL,
                included_in_briefing INTEGER
            )
        """)
        conn.commit()
        logger.debug("seen_items DB initialized")
    finally:
        conn.close()


def init_feedback_db() -> None:
    conn = _connect(FEEDBACK_DB)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                item_id TEXT,
                rating INTEGER,
                created_at TEXT
            )
        """)
        conn.commit()
        logger.debug("feedback DB initialized")
    finally:
        conn.close()


def get_seen_ids() -> set:
    conn = _connect(SEEN_ITEMS_DB)
    try:
        rows = conn.execute("SELECT id FROM seen_items").fetchall()
        return {row["id"] for row in rows}
    finally:
        conn.close()


def insert_seen_items(items: list, relevance_scores: Optional[dict] = None, included_ids: Optional[set] = None) -> None:
    """Insert items into seen_items. relevance_scores = {id: score}, included_ids = set of ids that passed filter."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    conn = _connect(SEEN_ITEMS_DB)
    try:
        for item in items:
            score = relevance_scores.get(item.id) if relevance_scores else None
            included = 1 if (included_ids and item.id in included_ids) else 0
            conn.execute(
                "INSERT OR IGNORE INTO seen_items (id, title, source, seen_at, relevance_score, included_in_briefing) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item.id, item.title, item.source, now, score, included)
            )
        conn.commit()
    finally:
        conn.close()


def insert_feedback(item_id: str, rating: int) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(FEEDBACK_DB)
    try:
        conn.execute(
            "INSERT INTO feedback (item_id, rating, created_at) VALUES (?, ?, ?)",
            (item_id, rating, now)
        )
        conn.commit()
    finally:
        conn.close()


def get_all_feedback() -> list:
    conn = _connect(FEEDBACK_DB)
    try:
        rows = conn.execute("SELECT * FROM feedback ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
