import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from google.genai import types

import config
from pipeline.models import AggregatedItem, EnrichedItem

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an AI research analyst creating personalized briefings. Given a news item and a user profile, produce a structured impact analysis tailored to that specific user.

Return ONLY valid JSON. No preamble. No markdown backticks. Use this exact structure:
{
  "what_it_is": "2-3 sentence plain English explanation",
  "why_it_matters": "2-3 sentences on technical or product significance",
  "impact_on_journey": "2-3 sentences specific to the user's profile, goals, and current tools",
  "action_items": ["specific thing to watch, try, or learn", "..."],
  "tldr": "one sentence summary"
}"""


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


def _build_user_prompt(item: AggregatedItem) -> str:
    return (
        f"User profile: {json.dumps(config.USER_PROFILE)}\n\n"
        f"Analyze this item:\n"
        f"Title: {item.title}\n"
        f"URL: {item.url}\n"
        f"Source: {item.source}\n"
        f"Category: {item.category}\n"
        f"Summary: {item.summary}"
    )


def _call_gemini(client: genai.Client, item: AggregatedItem) -> dict:
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=_build_user_prompt(item),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=8000,
                ),
            )
            raw = _strip_fences(_extract_text(response))
            return json.loads(raw)
        except Exception as e:
            if attempt == 0:
                logger.warning(f"Analyzer Gemini call failed for '{item.title}' (attempt 1): {e}. Retrying in 5s...")
                time.sleep(5)
            else:
                logger.error(f"Analyzer Gemini call failed for '{item.title}' (attempt 2): {e}. Skipping item.")
                return {}
    return {}


def _analyze_one(
    client: genai.Client,
    item: AggregatedItem,
    relevance_scores: dict,
    filter_meta: dict,
) -> EnrichedItem | None:
    """Analyze a single item. Returns EnrichedItem or None on failure."""
    analysis = _call_gemini(client, item)
    if not analysis:
        return None
    meta = filter_meta.get(item.id, {})
    return EnrichedItem(
        id=item.id,
        title=item.title,
        url=item.url,
        summary=item.summary,
        source=item.source,
        category=item.category,
        published_at=item.published_at,
        raw_score=item.raw_score,
        what_it_is=analysis.get("what_it_is", ""),
        why_it_matters=analysis.get("why_it_matters", ""),
        impact_on_journey=analysis.get("impact_on_journey", ""),
        action_items=analysis.get("action_items", []),
        tldr=analysis.get("tldr", ""),
        relevance_score=relevance_scores.get(item.id, 0.0),
        is_breakthrough=meta.get("is_breakthrough", False),
        one_line_reason=meta.get("one_line_reason", ""),
    )


def analyze_items(
    items: list[AggregatedItem],
    relevance_scores: dict,
    filter_meta: dict,
) -> list[EnrichedItem]:
    """Run per-item Gemini analysis in parallel. Returns list of EnrichedItem."""
    if not items:
        return []

    client = genai.Client(
        api_key=os.environ["GOOGLE_API_KEY"],
        http_options=types.HttpOptions(timeout=120_000),  # 120s per call — prevents indefinite hang
    )

    logger.info(f"Analyzer: processing {len(items)} items with {config.GEMINI_ANALYSIS_WORKERS} workers")
    enriched: list[EnrichedItem] = []

    with ThreadPoolExecutor(max_workers=config.GEMINI_ANALYSIS_WORKERS) as executor:
        futures = {
            executor.submit(_analyze_one, client, item, relevance_scores, filter_meta): item
            for item in items
        }
        for future in as_completed(futures):
            item = futures[future]
            result = future.result()
            if result is not None:
                logger.info(f"Analyzer: done — {item.title[:60]}")
                enriched.append(result)
            else:
                logger.warning(f"Analyzer: skipped — {item.title[:60]}")

    logger.info(f"Analyzer: enriched {len(enriched)}/{len(items)} items")
    return enriched
