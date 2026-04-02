# AI Pulse — Project Specification

## What We Are Building

AI Pulse is an automated daily briefing system that monitors the AI landscape, filters signal from noise using the Claude API, and delivers personalized impact analysis via email and a web dashboard. It runs on a daily schedule with zero manual intervention.

The system is built for someone actively on an AI learning journey — focused on LLM releases, research breakthroughs, AI tooling, and coding applications. It answers two questions every morning:

1. What actually happened in AI today that matters?
2. How does it affect me specifically?

## How It Works (Brief)

A Python pipeline runs daily in five sequential layers:

```
Data Sources → Aggregator → Claude Relevance Filter → Claude Impact Analyzer → Briefing Assembly → Email + Dashboard
```

- **Layer 1 — Aggregator**: Scrapes RSS feeds, blogs, HN, GitHub Trending into a normalized item list
- **Layer 2 — Relevance Filter**: Batches items to Claude API, scores 1-10, drops anything below threshold (default 6)
- **Layer 3 — Impact Analyzer**: Per-item Claude call producing personalized what/why/impact/actions breakdown
- **Layer 4 — Briefing Assembly**: Final Claude call for executive summary, items ranked and grouped by category
- **Layer 5 — Delivery**: Sends HTML email via Gmail SMTP, saves JSON briefing, serves via FastAPI dashboard

---

## 1. Data Sources (Layer 1)

All sources are public and require no authentication unless noted. Each has a daily item cap to control Claude API usage.

### 1.1 Research Breakthroughs

| Source | URL / Method | Daily Limit |
|---|---|---|
| ArXiv cs.AI | `http://arxiv.org/rss/cs.AI` (RSS) | 20 items |
| ArXiv cs.LG | `http://arxiv.org/rss/cs.LG` (RSS) | 20 items |
| ArXiv cs.CL | `http://arxiv.org/rss/cs.CL` (RSS) | 20 items |
| HuggingFace Papers | `https://huggingface.co/papers` (scrape) | 15 items |
| Google Research Blog | `https://research.google/blog/` (scrape) | 5 items |

### 1.2 LLM Models & Product Launches

| Source | URL / Method | Daily Limit |
|---|---|---|
| Anthropic Blog | `https://www.anthropic.com/news` (scrape) | 5 items |
| OpenAI Blog | `https://openai.com/news` (scrape) | 5 items |
| Google DeepMind | `https://deepmind.google/discover/blog/` (scrape) | 5 items |
| Mistral Blog | `https://mistral.ai/news/` (scrape) | 5 items |
| Meta AI Blog | `https://ai.meta.com/blog/` (scrape) | 5 items |

### 1.3 AI Tools & Coding

| Source | URL / Method | Daily Limit |
|---|---|---|
| Hacker News API | `https://hacker-news.firebaseio.com/v0/` (official API) — filter: score >= 100, title contains AI/ML/LLM/GPT/Claude | 15 items |
| GitHub Trending | `https://github.com/trending?l=python&since=daily` (scrape) | 10 repos |
| ProductHunt AI | `https://www.producthunt.com/topics/artificial-intelligence` (scrape) | 10 items |

### 1.4 Scraping Rules

- Use `httpx` for all HTTP requests, `BeautifulSoup4` for HTML parsing
- Set `User-Agent: Mozilla/5.0` header on all requests
- Add 1-second delay between requests to the same domain
- Timeout all requests at 10 seconds
- If any source fails (network error, parse error): log WARNING, skip that source, continue pipeline — never abort

### 1.5 Normalized Item Schema

Every item from every source must be converted to this dataclass before passing to the next layer:

```python
@dataclass
class AggregatedItem:
    id: str           # SHA256 hash of URL — used for deduplication
    title: str        # Title of article/paper/post
    url: str          # Canonical URL
    summary: str      # First 500 chars of description or abstract. Empty string if unavailable.
    source: str       # e.g. 'arxiv', 'hackernews', 'anthropic_blog', 'github_trending'
    category: str     # One of: 'research', 'models_releases', 'tools_products', 'coding_dev'
    published_at: str # ISO 8601 datetime string. Use today's date if not available.
    raw_score: int | None  # HN score or GitHub stars if available, else None
```

---

## 2. Deduplication & Seen Items Store

SQLite database at `data/seen_items.db`. Single table:

```sql
CREATE TABLE seen_items (
    id TEXT PRIMARY KEY,           -- SHA256 of URL
    title TEXT,
    source TEXT,
    seen_at TEXT,                  -- ISO 8601 datetime
    relevance_score REAL,          -- Claude score (0-10). NULL if not yet scored.
    included_in_briefing INTEGER   -- 1 if included in briefing, 0 if filtered out
);
```

**Logic**: Before passing items to Claude, filter out any whose `id` already exists in `seen_items`. After scoring, insert ALL items into `seen_items` regardless of whether they passed the relevance threshold.

---

## 3. Relevance Filter — Claude API (Layer 2)

Items not in `seen_items` are sent to Claude for relevance scoring. Use **batches of 20 items per API call** to minimize API usage. Expected ~5-7 API calls per day for this layer.

**Model to use for all Claude API calls in this project**: `claude-sonnet-4-20250514`

### 3.1 System Prompt (use verbatim)

```
You are an AI research analyst assistant. You evaluate AI news items for relevance to someone on an active AI learning journey. Their focus areas are: (1) LLM models and releases, (2) AI tools and products, (3) research breakthroughs that change how AI works, (4) AI for coding and developer tooling.

Score each item 1-10 where:
1-3 = routine/noise/incremental update
4-6 = worth knowing but not urgent
7-8 = significant development
9-10 = major breakthrough or paradigm shift (e.g. TurboQuant, GPT-4 level release, DeepSeek moment)

Also set is_breakthrough = true only for score >= 8 items that represent a genuine technical or product breakthrough, not just a new product version.

Return ONLY valid JSON. No preamble. No markdown backticks. Format:
{"items": [{"id": "...", "score": 7, "is_breakthrough": false, "one_line_reason": "..."}]}
```

### 3.2 User Prompt Format (per batch)

```
Score these {n} items for relevance:

{for each item}
ID: {item.id}
Title: {item.title}
Source: {item.source}
Summary: {item.summary}
{end for}
```

### 3.3 Threshold

Items with `score >= 6` proceed to Impact Analyzer. Items below are recorded in `seen_items` with `included_in_briefing = 0` and discarded. This should reduce 60-100 daily items down to ~10-20.

---

## 4. Impact Analyzer — Claude API (Layer 3)

Each item that passed the filter gets its own Claude API call for deep personalized analysis. These are NOT batched — one call per item.

### 4.1 User Profile (hardcoded in config.py, editable by user)

```python
USER_PROFILE = {
    "level": "intermediate learner — comfortable with Python and APIs, learning about LLMs and AI",
    "goals": [
        "understand key AI developments",
        "use AI tools in daily workflow",
        "learn to fine-tune and deploy models"
    ],
    "tools_used": ["Claude API", "Python", "VS Code", "Cursor"],
    "interests": [
        "LLM inference efficiency",
        "local model running",
        "AI coding assistants",
        "prompt engineering"
    ]
}
```

### 4.2 System Prompt (use verbatim)

```
You are an AI research analyst creating personalized briefings. Given a news item and a user profile, produce a structured impact analysis tailored to that specific user.

Return ONLY valid JSON. No preamble. No markdown backticks. Use this exact structure:
{
  "what_it_is": "2-3 sentence plain English explanation",
  "why_it_matters": "2-3 sentences on technical or product significance",
  "impact_on_journey": "2-3 sentences specific to the user's profile, goals, and current tools",
  "action_items": ["specific thing to watch, try, or learn", "..."],
  "tldr": "one sentence summary"
}
```

### 4.3 User Prompt Format

```
User profile: {json.dumps(USER_PROFILE)}

Analyze this item:
Title: {item.title}
URL: {item.url}
Source: {item.source}
Category: {item.category}
Summary: {item.summary}
```

### 4.4 Enriched Item Schema

```python
@dataclass
class EnrichedItem(AggregatedItem):
    what_it_is: str
    why_it_matters: str
    impact_on_journey: str
    action_items: list[str]
    tldr: str
    relevance_score: float   # carried from Layer 2
    is_breakthrough: bool    # carried from Layer 2
    one_line_reason: str     # carried from Layer 2
```

---

## 5. Briefing Assembly (Layer 4)

### 5.1 Executive Summary

One Claude API call at the start of assembly. Pass all enriched items' titles and tldr fields. System prompt:

```
You are summarizing today's AI news for a daily briefing. Given a list of today's top AI items, write exactly 3 sentences: what the most important development is, what the broader theme of today's news is, and one forward-looking observation. Be direct and specific. Return plain text only, no JSON.
```

### 5.2 Briefing Structure (order matters)

1. Executive summary (3 sentences from Claude)
2. **Breakthrough Alert section** — only rendered if any item has `is_breakthrough = True`. Lists those items first with a `🔥 BREAKTHROUGH` label.
3. Items grouped by category in this order:
   - Research Breakthroughs
   - LLM Models & Releases
   - AI Tools & Products
   - Coding & Dev
4. Within each category, items sorted by `relevance_score` descending
5. Footer: date, total items reviewed today, total items included

### 5.3 Per-Item Display Fields

For each item render: title, source, relevance_score badge, tldr, what_it_is, why_it_matters, impact_on_journey, action_items (as list), link to URL.

### 5.4 Briefing Storage Schema

Save to `data/briefings/YYYY-MM-DD.json`:

```json
{
  "date": "2026-04-01",
  "executive_summary": "...",
  "total_items_reviewed": 74,
  "total_items_included": 12,
  "items": [ /* list of EnrichedItem dicts */ ]
}
```

---

## 6. Delivery (Layer 5)

### 6.1 Email

Send via Gmail SMTP using Python's `smtplib`. All credentials from environment variables (never hardcoded).

**Required environment variables:**

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `GMAIL_USER` | Sender Gmail address (used as SMTP login) |
| `GMAIL_APP_PASSWORD` | Gmail App Password — NOT the account password. User generates this in Google Account → Security → 2-Step Verification → App Passwords |
| `RECIPIENT_EMAIL` | Destination email (can be same as GMAIL_USER) |

**Subject line format:**
```
🤖 AI Pulse — {date} | {item_count} items{' | 🔥 BREAKTHROUGH ALERT' if any is_breakthrough else ''}
```

**HTML email rules:**
- Self-contained HTML with inline styles only (no external CSS) — must render in Gmail
- Structure mirrors briefing structure from Section 5.2
- Score badge colors: 9-10 = `#10B981` (green), 7-8 = `#3B82F6` (blue), 6 = `#F59E0B` (yellow)
- Breakthrough items get a `#EF4444` red badge
- If `ENABLE_EMAIL = False` in config, skip send but still save JSON briefing

### 6.2 Web Dashboard

FastAPI backend + single HTML file frontend. **Not React** — pure HTML/CSS/vanilla JS served by FastAPI. Keep it simple.

**Start command:** `uvicorn dashboard.app:app --host 0.0.0.0 --port 8000`

**API Routes:**

| Route | Description |
|---|---|
| `GET /` | Serve `dashboard/static/index.html` |
| `GET /api/briefings` | List of all briefing dates + item counts (from `data/briefings/*.json`) |
| `GET /api/briefings/latest` | Full JSON of most recent briefing |
| `GET /api/briefings/{date}` | Full JSON for specific date (YYYY-MM-DD) |
| `GET /api/stats` | Aggregate stats: total items reviewed all-time, total briefings, top sources, breakthrough count |
| `POST /api/feedback` | Body: `{"item_id": str, "rating": int}` where rating is 1 (up) or -1 (down). Store in `data/feedback.db` |

**Frontend features:**
- Latest briefing loads on page open
- Sidebar list of past briefing dates — click to load any
- Breakthrough items highlighted at top
- Category tabs to filter items
- Thumbs up/down on each item — calls `POST /api/feedback`
- Stats panel: items reviewed today, breakthroughs this week, most active source
- Client-side search bar filtering items by title/summary (no backend call needed)

**Feedback database** `data/feedback.db`:
```sql
CREATE TABLE feedback (
    item_id TEXT,
    rating INTEGER,  -- 1 or -1
    created_at TEXT  -- ISO 8601
);
```

---

## 7. Scheduling & Entry Point

### 7.1 main.py

Single entry point orchestrating all layers in sequence. Accepts these CLI arguments:

```bash
python main.py                        # run for today
python main.py --date 2026-03-25      # backfill a specific date
python main.py --dry-run              # run full pipeline but skip email send
```

### 7.2 scheduler.py

Uses Python `schedule` library. Runs `main.py` every day at the time set in `config.py` (`BRIEFING_SEND_TIME`, default `"07:00"`). Also logs a health check line every morning.

```bash
python scheduler.py   # keep running in background
```

Alternatively, cron:
```
0 7 * * * cd /path/to/project && python main.py >> logs/cron.log 2>&1
```

---

## 8. Project File Structure

Create this exact structure:

```
ai-pulse/
├── main.py                        # Entry point — orchestrates all layers
├── scheduler.py                   # Daily schedule runner
├── config.py                      # All user-editable settings (see Section 10)
├── requirements.txt               # Pinned dependencies
├── .env.example                   # Template for required env vars
├── .env                           # Actual secrets — must be in .gitignore
├── .gitignore                     # Include: .env, data/, logs/, __pycache__/
├── README.md                      # Setup instructions (see Section 11)
├── pipeline/
│   ├── __init__.py
│   ├── models.py                  # AggregatedItem, EnrichedItem, Briefing dataclasses
│   ├── db.py                      # SQLite helpers for seen_items and feedback
│   ├── aggregator.py              # Layer 1 — all scrapers and RSS parsers
│   ├── filter.py                  # Layer 2 — Claude relevance scoring
│   ├── analyzer.py                # Layer 3 — Claude impact analysis
│   ├── assembler.py               # Layer 4 — briefing assembly + exec summary
│   └── delivery.py                # Layer 5 — email send + briefing JSON save
├── dashboard/
│   ├── app.py                     # FastAPI app with all routes
│   └── static/
│       └── index.html             # Single-page dashboard (HTML/CSS/vanilla JS)
├── data/                          # Created at runtime — not committed to git
│   ├── seen_items.db
│   ├── feedback.db
│   └── briefings/                 # YYYY-MM-DD.json files
└── logs/                          # Created at runtime — not committed to git
    └── pipeline.log
```

---

## 9. Python Dependencies (requirements.txt)

Pin to latest stable versions at time of creation:

| Package | Purpose |
|---|---|
| `anthropic` | Official Anthropic Python SDK |
| `httpx` | HTTP client for scraping and API calls |
| `beautifulsoup4` | HTML parsing for scraped pages |
| `feedparser` | RSS/Atom feed parsing |
| `schedule` | Job scheduler for scheduler.py |
| `fastapi` | Dashboard backend |
| `uvicorn` | ASGI server for FastAPI |
| `python-dotenv` | Load .env into environment |
| `jinja2` | HTML templating (also FastAPI dependency) |

> **Important**: Do NOT use async/await anywhere in the pipeline — keep everything synchronous for simplicity. FastAPI route handlers can also be sync (`def` not `async def`).

---

## 10. config.py — All User Settings

Every value a user might want to tune must be here with inline comments:

```python
# === Claude API ===
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"

# === Relevance Filter ===
RELEVANCE_THRESHOLD = 6.0       # Items scoring below this are dropped (scale 1-10)
MAX_ITEMS_PER_BRIEFING = 20     # Cap on total items in one briefing

# === Scheduling ===
BRIEFING_SEND_TIME = "07:00"    # 24h format, local time

# === Delivery ===
ENABLE_EMAIL = True             # Set False to skip email (useful for testing)
ENABLE_DASHBOARD = True

# === Logging ===
LOG_LEVEL = "INFO"              # DEBUG for verbose output during development

# === User Profile (personalization) ===
USER_PROFILE = {
    "level": "intermediate learner — comfortable with Python and APIs, learning about LLMs and AI",
    "goals": [
        "understand key AI developments",
        "use AI tools in daily workflow",
        "learn to fine-tune and deploy models"
    ],
    "tools_used": ["Claude API", "Python", "VS Code", "Cursor"],
    "interests": [
        "LLM inference efficiency",
        "local model running",
        "AI coding assistants",
        "prompt engineering"
    ]
}

# === Sources Toggle (set False to disable any source) ===
SOURCES_ENABLED = {
    "arxiv_ai": True,
    "arxiv_lg": True,
    "arxiv_cl": True,
    "huggingface_papers": True,
    "google_research": True,
    "anthropic_blog": True,
    "openai_blog": True,
    "deepmind_blog": True,
    "mistral_blog": True,
    "meta_ai_blog": True,
    "hackernews": True,
    "github_trending": True,
    "producthunt_ai": True,
}
```

---

## 11. Error Handling & Logging

### Logging Setup

Use Python's standard `logging` module. Log to both console and `logs/pipeline.log`.

Format: `%(asctime)s | %(levelname)s | %(module)s | %(message)s`

### Failure Rules

| Failure Type | Action |
|---|---|
| Data source fails (network/parse error) | Log WARNING, skip source, continue with others |
| Claude API call fails | Retry once after 5 seconds. If retry fails: log ERROR, skip that item/batch |
| Email send fails | Log ERROR with full traceback. Save JSON briefing regardless — delivery failure must not lose the briefing |
| Database locked or corrupt | Log CRITICAL and abort the run |
| Any unhandled exception in main() | Wrap top-level in try/except, log full traceback — never silently die |

---

## 12. README.md — Setup Instructions

Generate a README.md with these steps in order:

1. Clone repo and `cd` into it
2. `python -m venv venv && source venv/bin/activate` (Windows: `venv\Scripts\activate`)
3. `pip install -r requirements.txt`
4. `cp .env.example .env` — fill in `ANTHROPIC_API_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL`
5. Edit `config.py` — update `USER_PROFILE` and preferences to match your situation
6. `python main.py --dry-run` — test the full pipeline without sending email
7. `python main.py` — run for real
8. `python scheduler.py` — start daily schedule (or add cron entry from Section 7.2)
9. `uvicorn dashboard.app:app --host 0.0.0.0 --port 8000` — start dashboard

Include a note: to generate a Gmail App Password, go to Google Account → Security → 2-Step Verification → App Passwords. Create one for "Mail".

---

## 13. Out of Scope for This Build (Future Phases)

Do NOT build these now. Do not over-engineer for them:

- Feedback loop adjusting relevance scoring from thumbs up/down ratings
- Weekly digest email
- Trend tracking across weeks
- Twitter/X source integration
- Docker containerization
- Cloud deployment or hosting
- Dashboard authentication

---

## Build Instructions for Claude Code

Build the complete project as specified above. When something is ambiguous, prefer the simpler implementation. The goal is a working system that runs end-to-end, not a perfect one.

Start with `pipeline/models.py` and `pipeline/db.py` (foundation), then build each pipeline layer in order (aggregator → filter → analyzer → assembler → delivery), then `main.py`, then the dashboard, then `scheduler.py`.
