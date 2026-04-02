# AI Pulse

Automated daily AI briefing system. Monitors the AI landscape, filters signal from noise using Gemini, and delivers personalized impact analysis via email and a web dashboard.

## Setup

### 1. Clone and enter the project

```bash
git clone <repo-url>
cd ai-pulse
```

### 2. Install dependencies with uv

```bash
uv sync
```

> Install uv if needed: `pip install uv` or see [uv docs](https://docs.astral.sh/uv/)

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `GOOGLE_API_KEY` — your Google AI API key (get it from [Google AI Studio](https://aistudio.google.com/apikey))
- `GMAIL_USER` — your Gmail address (used as SMTP sender)
- `GMAIL_APP_PASSWORD` — Gmail App Password (**not** your account password)
- `RECIPIENT_EMAIL` — destination email address

> **Gmail App Password**: Go to Google Account → Security → 2-Step Verification → App Passwords. Create one for "Mail". Use that 16-character password here.

### 4. Customize your profile

Edit `config.py` — update `USER_PROFILE` with your background, goals, and tools to personalize the impact analysis.

### 5. Dry run (no email sent)

```bash
uv run python main.py --dry-run
```

This runs the full pipeline — scraping, Gemini scoring, Gemini analysis, briefing assembly — but skips email delivery. The JSON briefing is saved to `data/briefings/YYYY-MM-DD.json`.

### 6. Full run

```bash
uv run python main.py
```

### 7. Backfill a specific date

```bash
uv run python main.py --date 2026-03-25
```

### 8. Start the daily scheduler

```bash
uv run python scheduler.py
```

Runs `main.py` every day at the time set in `config.py` (`BRIEFING_SEND_TIME`, default `07:00`).

Alternatively, add a cron entry:
```
0 7 * * * cd /path/to/ai-pulse && uv run python main.py >> logs/cron.log 2>&1
```

### 9. Start the web dashboard

```bash
uv run uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

---

## Configuration

All user-tunable settings are in `config.py`:

| Setting | Default | Description |
|---|---|---|
| `GEMINI_MODEL` | `gemini-2.5-pro` | Gemini model to use |
| `RELEVANCE_THRESHOLD` | `6.0` | Minimum score (1-10) to include an item |
| `MAX_ITEMS_PER_BRIEFING` | `20` | Maximum items in one briefing |
| `BRIEFING_SEND_TIME` | `"07:00"` | Daily send time (24h, local) |
| `ENABLE_EMAIL` | `True` | Set `False` to skip email |
| `SOURCES_ENABLED` | all `True` | Toggle individual sources on/off |

---

## Project Structure

```
ai-pulse/
├── main.py              # Entry point
├── scheduler.py         # Daily scheduler
├── config.py            # User settings
├── pyproject.toml       # uv dependencies
├── pipeline/
│   ├── models.py        # Data models
│   ├── db.py            # SQLite helpers
│   ├── aggregator.py    # Layer 1: data collection
│   ├── filter.py        # Layer 2: Gemini relevance scoring
│   ├── analyzer.py      # Layer 3: Gemini impact analysis
│   ├── assembler.py     # Layer 4: briefing assembly
│   └── delivery.py      # Layer 5: email delivery
└── dashboard/
    ├── app.py           # FastAPI backend
    └── static/
        └── index.html   # Web dashboard
```
