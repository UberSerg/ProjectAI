"""Source-specific known_at policies — never fabricate historical availability."""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.intelligence.news.registry import KnownAtPolicy


def compute_known_at(
    *,
    policy: KnownAtPolicy,
    published_at: datetime | None,
    observed_at: datetime,
) -> tuple[datetime, str]:
    """Return (known_at, known_at_basis).

    ``MAX_PUBLISHED_OBSERVED``: Kraken may not treat an item as decision-available
    before both publisher claim and first observation. Live ingest therefore uses
    ``max(published_at, observed_at)`` — past pubDate does **not** invent historical
    knowledge at the publication instant.

    ``OBSERVED_ONLY``: ignore publisher clock; known_at = observed_at.
    """
    obs = _ensure_utc(observed_at)
    if policy == "OBSERVED_ONLY" or published_at is None:
        return obs, "OBSERVED_AT"
    pub = _ensure_utc(published_at)
    known = max(pub, obs)
    return known, "MAX_PUBLISHED_OBSERVED"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
