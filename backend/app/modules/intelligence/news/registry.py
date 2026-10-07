"""Allowlisted news / disclosure source registry.

Arbitrary user-supplied URLs are rejected (SSRF prevention).
Fetch is permitted only for hosts declared on a registered source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

KnownAtPolicy = Literal[
    "MAX_PUBLISHED_OBSERVED",
    "OBSERVED_ONLY",
]


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    """Immutable allowlist entry for one production feed."""

    source_id: str
    provider: str
    source_type: str
    adapter: str
    feed_url: str
    allowed_hosts: tuple[str, ...]
    known_at_policy: KnownAtPolicy
    language: str
    rate_limit_seconds: float
    max_items: int
    notes: str
    enabled: bool = True


_SOURCES: dict[str, SourceDefinition] = {
    "cbr_press_ru": SourceDefinition(
        source_id="cbr_press_ru",
        provider="cbr",
        source_type="PRESS_RELEASE",
        adapter="cbr_rss",
        feed_url="https://www.cbr.ru/rss/RssPress",
        allowed_hosts=("www.cbr.ru", "cbr.ru"),
        known_at_policy="MAX_PUBLISHED_OBSERVED",
        language="ru",
        rate_limit_seconds=1.0,
        max_items=40,
        notes="Official Bank of Russia press-release RSS (public).",
    ),
    "cbr_news_ru": SourceDefinition(
        source_id="cbr_news_ru",
        provider="cbr",
        source_type="NEWS",
        adapter="cbr_rss",
        feed_url="https://www.cbr.ru/rss/RssNews",
        allowed_hosts=("www.cbr.ru", "cbr.ru"),
        known_at_policy="MAX_PUBLISHED_OBSERVED",
        language="ru",
        rate_limit_seconds=1.0,
        max_items=40,
        notes="Official Bank of Russia site-news RSS (public).",
    ),
    "moex_sitenews": SourceDefinition(
        source_id="moex_sitenews",
        provider="moex",
        source_type="EXCHANGE_NEWS",
        adapter="moex_sitenews",
        feed_url="https://iss.moex.com/iss/sitenews.json",
        allowed_hosts=("iss.moex.com", "www.moex.com", "moex.com"),
        known_at_policy="MAX_PUBLISHED_OBSERVED",
        language="ru",
        rate_limit_seconds=0.5,
        max_items=50,
        notes="MOEX ISS public sitenews JSON (structured; preferred over full RSS dump).",
    ),
}


def list_sources(*, enabled_only: bool = True) -> tuple[SourceDefinition, ...]:
    items = sorted(_SOURCES.values(), key=lambda s: s.source_id)
    if enabled_only:
        items = [s for s in items if s.enabled]
    return tuple(items)


def get_source(source_id: str) -> SourceDefinition:
    try:
        return _SOURCES[source_id]
    except KeyError as exc:
        raise KeyError(f"source not in allowlist: {source_id!r}") from exc


def is_host_allowed(source: SourceDefinition, host: str) -> bool:
    host_l = host.lower().rstrip(".")
    return any(host_l == allowed.lower() or host_l.endswith("." + allowed.lower()) for allowed in source.allowed_hosts)
