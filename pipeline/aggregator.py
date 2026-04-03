import calendar
import hashlib
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Optional

import feedparser
import httpx
from bs4 import BeautifulSoup

from pipeline.models import AggregatedItem
import config

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 10

# Per-domain rate limiting — thread-safe
_last_request_time: dict[str, float] = {}
_domain_locks: dict[str, threading.Lock] = {}
_domain_locks_meta = threading.Lock()


def _get_domain_lock(domain: str) -> threading.Lock:
    with _domain_locks_meta:
        if domain not in _domain_locks:
            _domain_locks[domain] = threading.Lock()
        return _domain_locks[domain]


def _http_get(url: str, domain: str) -> Optional[httpx.Response]:
    """Rate-limited HTTP GET — 1 second delay per domain, thread-safe."""
    with _get_domain_lock(domain):
        elapsed = time.time() - _last_request_time.get(domain, 0)
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _last_request_time[domain] = time.time()
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp
    except Exception as e:
        logger.warning(f"HTTP error fetching {url}: {e}")
        return None


def _make_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _truncate(text: str, n: int = 500) -> str:
    return (text or "")[:n]


_DATE_RE = re.compile(
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}'
    r'|\d{4}-\d{2}-\d{2}'
)
_DATE_FORMATS = ["%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y", "%Y-%m-%d"]


def _extract_date_from_text(text: str) -> Optional[str]:
    """Try to parse a date out of arbitrary text. Returns YYYY-MM-DD or None."""
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    raw = m.group(0).replace(",", "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _is_recent(published_at: str, lookback_days: int) -> bool:
    """Return True if published_at is within the last lookback_days days."""
    try:
        if len(published_at) == 10:
            pub_date = datetime.strptime(published_at, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            pub_date = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        return pub_date >= cutoff
    except Exception:
        return True  # If we can't parse, include it


# ── RSS helpers ──────────────────────────────────────────────────────────────

def _parse_rss(feed_url: str, source: str, category: str, limit: int) -> list[AggregatedItem]:
    try:
        feed = feedparser.parse(feed_url)
        items = []
        for entry in feed.entries[:limit]:
            url = entry.get("link", "")
            if not url:
                continue
            summary = _truncate(entry.get("summary", entry.get("description", "")))
            if entry.get("published_parsed"):
                ts = calendar.timegm(entry.published_parsed)
                pub = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
            else:
                pub = entry.get("published", _today_iso())[:10] if entry.get("published") else _today_iso()
            items.append(AggregatedItem(
                id=_make_id(url),
                title=entry.get("title", ""),
                url=url,
                summary=summary,
                source=source,
                category=category,
                published_at=pub,
                raw_score=None,
            ))
        logger.info(f"{source}: fetched {len(items)} items")
        return items
    except Exception as e:
        logger.warning(f"{source}: RSS parse error — {e}")
        return []


# ── ArXiv ─────────────────────────────────────────────────────────────────────

def fetch_arxiv_ai() -> list[AggregatedItem]:
    return _parse_rss("http://arxiv.org/rss/cs.AI", "arxiv_ai", "research", 20)

def fetch_arxiv_lg() -> list[AggregatedItem]:
    return _parse_rss("http://arxiv.org/rss/cs.LG", "arxiv_lg", "research", 20)

def fetch_arxiv_cl() -> list[AggregatedItem]:
    return _parse_rss("http://arxiv.org/rss/cs.CL", "arxiv_cl", "research", 20)


# ── HuggingFace Papers ────────────────────────────────────────────────────────

def fetch_huggingface_papers() -> list[AggregatedItem]:
    source = "huggingface_papers"
    resp = _http_get("https://huggingface.co/papers", "huggingface.co")
    if not resp:
        return []
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        for article in soup.select("article")[:15]:
            # First <a> is a thumbnail with no text; title lives in the heading
            heading = article.find(["h1", "h2", "h3", "h4"])
            title = heading.get_text(strip=True) if heading else ""
            if not title:
                continue
            a = article.find("a", href=lambda h: h and h.startswith("/papers/"))
            if not a:
                continue
            href = a["href"]
            url = f"https://huggingface.co{href}"
            summary = _truncate(article.get_text(" ", strip=True))
            items.append(AggregatedItem(
                id=_make_id(url),
                title=title,
                url=url,
                summary=summary,
                source=source,
                category="research",
                published_at=_today_iso(),
                raw_score=None,
            ))
        logger.info(f"{source}: fetched {len(items)} items")
        return items
    except Exception as e:
        logger.warning(f"{source}: parse error — {e}")
        return []


# ── Google Research Blog ──────────────────────────────────────────────────────

def fetch_google_research() -> list[AggregatedItem]:
    source = "google_research"
    resp = _http_get("https://research.google/blog/", "research.google")
    if not resp:
        return []
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        for a in soup.select("a[href]")[:30]:
            href = a["href"]
            if "/blog/" not in href:
                continue
            url = href if href.startswith("http") else f"https://research.google{href}"
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            items.append(AggregatedItem(
                id=_make_id(url),
                title=title,
                url=url,
                summary="",
                source=source,
                category="research",
                published_at=_today_iso(),
                raw_score=None,
            ))
            if len(items) >= 5:
                break
        logger.info(f"{source}: fetched {len(items)} items")
        return items
    except Exception as e:
        logger.warning(f"{source}: parse error — {e}")
        return []


# ── Company blogs (generic scraper) ──────────────────────────────────────────

def _scrape_blog(url: str, domain: str, source: str, category: str, limit: int,
                 link_selector: str, base_url: str = "") -> list[AggregatedItem]:
    resp = _http_get(url, domain)
    if not resp:
        return []
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        seen_urls: set[str] = set()
        for a in soup.select(link_selector):
            href = a.get("href", "")
            if not href:
                continue
            full_url = href if href.startswith("http") else f"{base_url}{href}"
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            raw_title = a.get_text(strip=True)
            if not raw_title or len(raw_title) < 10:
                continue
            # Strip leading noise: "ProductFeb 17, 2026" or "Mar 31, 2026Announcements"
            title = re.sub(
                r'^(?:(?:Product|Announcements?|Research|News|Blog)\s*)?'
                r'(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\s*)?'
                r'(?:(?:Product|Announcements?|Research|News|Blog)\s*)?',
                '', raw_title
            ).strip() or raw_title
            # Try to find a nearby <time datetime="..."> element, then fall back to text parsing
            pub_date = None
            parent = a.parent
            for _ in range(6):
                if parent is None:
                    break
                time_el = parent.find("time", attrs={"datetime": True})
                if time_el:
                    raw_dt = time_el["datetime"]
                    pub_date = raw_dt[:10] if len(raw_dt) >= 10 else None
                    break
                parent = getattr(parent, "parent", None)
            if not pub_date:
                # Try extracting date from the link text or nearest ancestor text
                pub_date = _extract_date_from_text(a.get_text())
            if not pub_date:
                parent = a.parent
                for _ in range(4):
                    if parent is None:
                        break
                    pub_date = _extract_date_from_text(parent.get_text(" ", strip=True))
                    if pub_date:
                        break
                    parent = getattr(parent, "parent", None)
            pub_date = pub_date or _today_iso()
            items.append(AggregatedItem(
                id=_make_id(full_url),
                title=title,
                url=full_url,
                summary="",
                source=source,
                category=category,
                published_at=pub_date,
                raw_score=None,
            ))
            if len(items) >= limit:
                break
        logger.info(f"{source}: fetched {len(items)} items")
        return items
    except Exception as e:
        logger.warning(f"{source}: parse error — {e}")
        return []


def fetch_anthropic_blog() -> list[AggregatedItem]:
    return _scrape_blog(
        "https://www.anthropic.com/news", "anthropic.com",
        "anthropic_blog", "models_releases", 5,
        "a[href*='/news/']", "https://www.anthropic.com"
    )

def fetch_openai_blog() -> list[AggregatedItem]:
    return _scrape_blog(
        "https://openai.com/news", "openai.com",
        "openai_blog", "models_releases", 5,
        "a[href*='/index/']", "https://openai.com"
    )

def fetch_deepmind_blog() -> list[AggregatedItem]:
    return _scrape_blog(
        "https://deepmind.google/discover/blog/", "deepmind.google",
        "deepmind_blog", "models_releases", 5,
        "a[href*='/blog/']", "https://deepmind.google"
    )

def fetch_mistral_blog() -> list[AggregatedItem]:
    return _scrape_blog(
        "https://mistral.ai/news/", "mistral.ai",
        "mistral_blog", "models_releases", 5,
        "a[href*='/news/']", "https://mistral.ai"
    )

def fetch_meta_ai_blog() -> list[AggregatedItem]:
    return _scrape_blog(
        "https://ai.meta.com/blog/", "ai.meta.com",
        "meta_ai_blog", "models_releases", 5,
        "a[href*='/blog/']", "https://ai.meta.com"
    )


# ── Hacker News API ───────────────────────────────────────────────────────────

AI_KEYWORDS = {"ai", "ml", "llm", "gpt", "claude", "machine learning", "deep learning",
               "neural", "transformer", "diffusion", "embedding", "inference", "fine-tun"}

def fetch_hackernews() -> list[AggregatedItem]:
    source = "hackernews"
    base = "https://hacker-news.firebaseio.com/v0"
    resp = _http_get(f"{base}/topstories.json", "hacker-news.firebaseio.com")
    if not resp:
        return []
    try:
        story_ids = resp.json()[:200]
        items = []
        for sid in story_ids:
            if len(items) >= 15:
                break
            sr = _http_get(f"{base}/item/{sid}.json", "hacker-news.firebaseio.com")
            if not sr:
                continue
            story = sr.json()
            if not story or story.get("type") != "story":
                continue
            score = story.get("score", 0)
            if score < 100:
                continue
            title = story.get("title", "")
            if not any(kw in title.lower() for kw in AI_KEYWORDS):
                continue
            url = story.get("url") or f"https://news.ycombinator.com/item?id={sid}"
            items.append(AggregatedItem(
                id=_make_id(url),
                title=title,
                url=url,
                summary=_truncate(story.get("text", "")),
                source=source,
                category="tools_products",
                published_at=_today_iso(),
                raw_score=score,
            ))
        logger.info(f"{source}: fetched {len(items)} items")
        return items
    except Exception as e:
        logger.warning(f"{source}: error — {e}")
        return []


# ── GitHub Trending ───────────────────────────────────────────────────────────

def fetch_github_trending() -> list[AggregatedItem]:
    source = "github_trending"
    resp = _http_get("https://github.com/trending?l=python&since=daily", "github.com")
    if not resp:
        return []
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        for repo_div in soup.select("article.Box-row")[:10]:
            a = repo_div.select_one("h2 a")
            if not a:
                continue
            href = a["href"].strip()
            url = f"https://github.com{href}"
            title = href.strip("/").replace("/", " / ")
            desc_el = repo_div.select_one("p")
            summary = _truncate(desc_el.get_text(strip=True) if desc_el else "")
            stars_el = repo_div.select_one("a[href*='stargazers']")
            stars = None
            if stars_el:
                try:
                    stars = int(stars_el.get_text(strip=True).replace(",", ""))
                except ValueError:
                    pass
            items.append(AggregatedItem(
                id=_make_id(url),
                title=title,
                url=url,
                summary=summary,
                source=source,
                category="coding_dev",
                published_at=_today_iso(),
                raw_score=stars,
            ))
        logger.info(f"{source}: fetched {len(items)} items")
        return items
    except Exception as e:
        logger.warning(f"{source}: parse error — {e}")
        return []


# ── ProductHunt AI ────────────────────────────────────────────────────────────

def fetch_producthunt_ai() -> list[AggregatedItem]:
    source = "producthunt_ai"
    resp = _http_get("https://www.producthunt.com/topics/artificial-intelligence", "producthunt.com")
    if not resp:
        return []
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        seen: set[str] = set()
        for a in soup.select("a[href*='/posts/']"):
            href = a["href"]
            url = href if href.startswith("http") else f"https://www.producthunt.com{href}"
            if url in seen:
                continue
            seen.add(url)
            title = a.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            items.append(AggregatedItem(
                id=_make_id(url),
                title=title,
                url=url,
                summary="",
                source=source,
                category="tools_products",
                published_at=_today_iso(),
                raw_score=None,
            ))
            if len(items) >= 10:
                break
        logger.info(f"{source}: fetched {len(items)} items")
        return items
    except Exception as e:
        logger.warning(f"{source}: parse error — {e}")
        return []


# ── Main aggregator ───────────────────────────────────────────────────────────

SOURCE_FETCHERS = {
    "arxiv_ai": fetch_arxiv_ai,
    "arxiv_lg": fetch_arxiv_lg,
    "arxiv_cl": fetch_arxiv_cl,
    "huggingface_papers": fetch_huggingface_papers,
    "google_research": fetch_google_research,
    "anthropic_blog": fetch_anthropic_blog,
    "openai_blog": fetch_openai_blog,
    "deepmind_blog": fetch_deepmind_blog,
    "mistral_blog": fetch_mistral_blog,
    "meta_ai_blog": fetch_meta_ai_blog,
    "hackernews": fetch_hackernews,
    "github_trending": fetch_github_trending,
    "producthunt_ai": fetch_producthunt_ai,
}


def _run_fetcher(source_key: str, fetcher) -> tuple[str, list[AggregatedItem]]:
    try:
        return source_key, fetcher()
    except Exception as e:
        logger.warning(f"Source {source_key} failed unexpectedly: {e}")
        return source_key, []


def aggregate(seen_ids: set) -> list[AggregatedItem]:
    """Fetch all enabled sources in parallel, deduplicate, return new items."""
    enabled = {
        k: v for k, v in SOURCE_FETCHERS.items()
        if config.SOURCES_ENABLED.get(k, True)
    }

    if not enabled:
        return []

    # Run all sources concurrently — I/O bound so threads work well
    results: dict[str, list[AggregatedItem]] = {}
    with ThreadPoolExecutor(max_workers=min(len(enabled), 8)) as executor:
        futures = {executor.submit(_run_fetcher, k, fn): k for k, fn in enabled.items()}
        for future in as_completed(futures):
            source_key, items = future.result()
            results[source_key] = items

    # Deduplicate in deterministic SOURCE_FETCHERS order
    all_items: list[AggregatedItem] = []
    seen_in_run: set[str] = set(seen_ids)
    for key in SOURCE_FETCHERS:
        for item in results.get(key, []):
            if item.id not in seen_in_run:
                seen_in_run.add(item.id)
                all_items.append(item)

    logger.info(f"Aggregator: {len(all_items)} new items after deduplication")

    # Filter out items older than LOOKBACK_DAYS
    recent_items = [i for i in all_items if _is_recent(i.published_at, config.LOOKBACK_DAYS)]
    dropped = len(all_items) - len(recent_items)
    if dropped:
        logger.info(f"Aggregator: dropped {dropped} items older than {config.LOOKBACK_DAYS} days")
    logger.info(f"Aggregator: {len(recent_items)} items remaining after date filter")
    return recent_items
