import json
import logging
import os
import re
import time

from google import genai
from google.genai import types

import config
from pipeline.models import AggregatedItem

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an AI research analyst assistant. You evaluate AI news items for relevance to someone on an active AI learning journey. Their focus areas are: (1) LLM models and releases, (2) AI tools and products, (3) research breakthroughs that change how AI works, (4) AI for coding and developer tooling.

Score each item 1-10 where:
1-3 = routine/noise/incremental update
4-6 = worth knowing but not urgent
7-8 = significant development
9-10 = major breakthrough or paradigm shift (e.g. TurboQuant, GPT-4 level release, DeepSeek moment)

Also set is_breakthrough = true only for score >= 8 items that represent a genuine technical or product breakthrough, not just a new product version.

Return ONLY valid JSON. No preamble. No markdown backticks. Format:
{"items": [{"id": "...", "score": 7, "is_breakthrough": false, "one_line_reason": "..."}]}"""


def _strip_fences(text: str) -> str:
    """Strip markdown code fences Gemini sometimes wraps around JSON responses."""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return text.strip()


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


def _build_user_prompt(items: list[AggregatedItem]) -> str:
    lines = [f"Score these {len(items)} items for relevance:\n"]
    for item in items:
        lines.append(f"ID: {item.id}")
        lines.append(f"Title: {item.title}")
        lines.append(f"Source: {item.source}")
        lines.append(f"Summary: {item.summary}")
        lines.append("")
    return "\n".join(lines)


def _call_gemini(client: genai.Client, items: list[AggregatedItem]) -> dict:
    """Call Gemini for a batch of items. Returns {id: {score, is_breakthrough, one_line_reason}}."""
    user_prompt = _build_user_prompt(items)
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=16000,
                ),
            )
            raw = _strip_fences(_extract_text(response))
            data = json.loads(raw)
            result = {}
            for entry in data.get("items", []):
                result[entry["id"]] = {
                    "score": float(entry.get("score", 0)),
                    "is_breakthrough": bool(entry.get("is_breakthrough", False)),
                    "one_line_reason": entry.get("one_line_reason", ""),
                }
            return result
        except Exception as e:
            if attempt == 0:
                logger.warning(f"Filter Gemini call failed (attempt 1): {e}. Retrying in 5s...")
                time.sleep(5)
            else:
                logger.error(f"Filter Gemini call failed (attempt 2): {e}. Skipping batch.")
                return {}
    return {}


def filter_items(items: list[AggregatedItem]) -> tuple[list, dict, dict]:
    """
    Score items via Gemini. Return:
      - passing_items: items with score >= RELEVANCE_THRESHOLD
      - relevance_scores: {id: score} for ALL items
      - metadata: {id: {is_breakthrough, one_line_reason}} for ALL scored items
    """
    if not items:
        return [], {}, {}

    client = genai.Client(
        api_key=os.environ["GOOGLE_API_KEY"],
        http_options=types.HttpOptions(timeout=120_000),
    )
    batch_size = 20
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]

    all_scores: dict[str, float] = {}
    all_meta: dict[str, dict] = {}

    for i, batch in enumerate(batches):
        logger.info(f"Filter: scoring batch {i + 1}/{len(batches)} ({len(batch)} items)")
        results = _call_gemini(client, batch)
        for item_id, data in results.items():
            all_scores[item_id] = data["score"]
            all_meta[item_id] = {
                "is_breakthrough": data["is_breakthrough"],
                "one_line_reason": data["one_line_reason"],
            }

    threshold = config.RELEVANCE_THRESHOLD
    passing = [item for item in items if all_scores.get(item.id, 0) >= threshold]
    logger.info(f"Filter: {len(passing)}/{len(items)} items passed threshold {threshold}")
    return passing, all_scores, all_meta
