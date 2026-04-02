from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class AggregatedItem:
    id: str                     # SHA256 hash of URL — used for deduplication
    title: str                  # Title of article/paper/post
    url: str                    # Canonical URL
    summary: str                # First 500 chars of description or abstract
    source: str                 # e.g. 'arxiv', 'hackernews', 'anthropic_blog'
    category: str               # One of: 'research', 'models_releases', 'tools_products', 'coding_dev'
    published_at: str           # ISO 8601 datetime string
    raw_score: Optional[int]    # HN score or GitHub stars if available, else None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EnrichedItem(AggregatedItem):
    what_it_is: str = ""
    why_it_matters: str = ""
    impact_on_journey: str = ""
    action_items: list = field(default_factory=list)
    tldr: str = ""
    relevance_score: float = 0.0
    is_breakthrough: bool = False
    one_line_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
