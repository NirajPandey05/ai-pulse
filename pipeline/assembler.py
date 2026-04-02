import json
import logging
import os
import time
from pathlib import Path

from google import genai
from google.genai import types

import config
from pipeline.models import EnrichedItem

logger = logging.getLogger(__name__)

BRIEFINGS_DIR = Path(__file__).parent.parent / "data" / "briefings"

EXEC_SUMMARY_SYSTEM = (
    "You are summarizing today's AI news for a daily briefing. Given a list of today's top AI items, "
    "write exactly 3 sentences: what the most important development is, what the broader theme of today's "
    "news is, and one forward-looking observation. Be direct and specific. Return plain text only, no JSON."
)

CATEGORY_ORDER = ["research", "models_releases", "tools_products", "coding_dev"]
CATEGORY_LABELS = {
    "research": "Research Breakthroughs",
    "models_releases": "LLM Models & Releases",
    "tools_products": "AI Tools & Products",
    "coding_dev": "Coding & Dev",
}


def _extract_text(response) -> str:
    """Extract text from Gemini response with null-safe fallback."""
    if response.text is not None:
        return response.text
    try:
        for part in (response.candidates[0].content.parts or []):
            if not getattr(part, "thought", False) and part.text:
                return part.text
    except (AttributeError, IndexError, TypeError):
        pass
    return ""


def _get_executive_summary(client: genai.Client, items: list[EnrichedItem]) -> str:
    if not items:
        return "No items to summarize today."
    user_content = "Today's top AI items:\n\n"
    for item in items:
        user_content += f"- {item.title}: {item.tldr}\n"
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=EXEC_SUMMARY_SYSTEM,
                    max_output_tokens=4000,
                ),
            )
            return _extract_text(response).strip()
        except Exception as e:
            if attempt == 0:
                logger.warning(f"Executive summary failed (attempt 1): {e}. Retrying in 5s...")
                time.sleep(5)
            else:
                logger.error(f"Executive summary failed (attempt 2): {e}")
                return "Executive summary unavailable."
    return "Executive summary unavailable."


def assemble(items: list[EnrichedItem], run_date: str, total_reviewed: int) -> dict:
    """Build the briefing dict and save to data/briefings/YYYY-MM-DD.json."""
    client = genai.Client(
        api_key=os.environ["GOOGLE_API_KEY"],
        http_options=types.HttpOptions(timeout=120_000),
    )

    # Cap items
    capped = sorted(items, key=lambda x: x.relevance_score, reverse=True)[:config.MAX_ITEMS_PER_BRIEFING]

    logger.info(f"Assembler: generating executive summary for {len(capped)} items")
    exec_summary = _get_executive_summary(client, capped)

    # Group by category, sort by relevance_score desc within each
    grouped: dict[str, list] = {cat: [] for cat in CATEGORY_ORDER}
    for item in capped:
        cat = item.category if item.category in grouped else "tools_products"
        grouped[cat].append(item)
    for cat in grouped:
        grouped[cat].sort(key=lambda x: x.relevance_score, reverse=True)

    # Ordered flat list for the briefing
    ordered_items = []
    for cat in CATEGORY_ORDER:
        ordered_items.extend(grouped[cat])

    briefing = {
        "date": run_date,
        "executive_summary": exec_summary,
        "total_items_reviewed": total_reviewed,
        "total_items_included": len(ordered_items),
        "items": [item.to_dict() for item in ordered_items],
    }

    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BRIEFINGS_DIR / f"{run_date}.json"
    out_path.write_text(json.dumps(briefing, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Assembler: briefing saved to {out_path}")

    return briefing
