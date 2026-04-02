import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.db import init_feedback_db, insert_feedback, get_all_feedback

logger = logging.getLogger(__name__)

BRIEFINGS_DIR = Path(__file__).parent.parent / "data" / "briefings"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AI Pulse Dashboard")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

init_feedback_db()


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/briefings")
def list_briefings():
    """List all briefing dates with item counts."""
    if not BRIEFINGS_DIR.exists():
        return JSONResponse([])
    result = []
    for f in sorted(BRIEFINGS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({
                "date": data["date"],
                "total_items_included": data.get("total_items_included", 0),
                "total_items_reviewed": data.get("total_items_reviewed", 0),
            })
        except Exception:
            pass
    return JSONResponse(result)


@app.get("/api/briefings/latest")
def latest_briefing():
    if not BRIEFINGS_DIR.exists():
        raise HTTPException(status_code=404, detail="No briefings found")
    files = sorted(BRIEFINGS_DIR.glob("*.json"), reverse=True)
    if not files:
        raise HTTPException(status_code=404, detail="No briefings found")
    data = json.loads(files[0].read_text(encoding="utf-8"))
    return JSONResponse(data)


@app.get("/api/briefings/{date}")
def get_briefing(date: str):
    path = BRIEFINGS_DIR / f"{date}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Briefing for {date} not found")
    data = json.loads(path.read_text(encoding="utf-8"))
    return JSONResponse(data)


@app.get("/api/stats")
def get_stats():
    """Aggregate stats across all briefings."""
    if not BRIEFINGS_DIR.exists():
        return JSONResponse({"total_items_reviewed": 0, "total_briefings": 0,
                             "top_sources": {}, "breakthrough_count": 0})

    total_reviewed = 0
    total_briefings = 0
    source_counts: dict = {}
    breakthrough_count = 0

    for f in BRIEFINGS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            total_reviewed += data.get("total_items_reviewed", 0)
            total_briefings += 1
            for item in data.get("items", []):
                src = item.get("source", "unknown")
                source_counts[src] = source_counts.get(src, 0) + 1
                if item.get("is_breakthrough"):
                    breakthrough_count += 1
        except Exception:
            pass

    top_sources = dict(sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:5])
    return JSONResponse({
        "total_items_reviewed": total_reviewed,
        "total_briefings": total_briefings,
        "top_sources": top_sources,
        "breakthrough_count": breakthrough_count,
    })


class FeedbackRequest(BaseModel):
    item_id: str
    rating: int  # 1 or -1


@app.post("/api/feedback")
def post_feedback(body: FeedbackRequest):
    if body.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be 1 or -1")
    insert_feedback(body.item_id, body.rating)
    return JSONResponse({"status": "ok"})
