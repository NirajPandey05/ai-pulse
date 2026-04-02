# === Gemini API ===
GEMINI_MODEL = "gemini-2.5-pro"

# === Relevance Filter ===
RELEVANCE_THRESHOLD = 6.0       # Items scoring below this are dropped (scale 1-10)
MAX_ITEMS_PER_BRIEFING = 20     # Cap on total items in one briefing
LOOKBACK_DAYS = 3               # Only include items published within this many days

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
