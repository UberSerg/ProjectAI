"""Shared helpers for independent SignalOutputV1 adapters.

Models must not import each other. Missing evidence => UNKNOWN/ABSTAIN, never fabricated zero.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.modules.intelligence.contracts.provenance import known_at_allows
from app.modules.intelligence.contracts.signal import SignalState

POSITIVE_THRESHOLD = 0.20
NEGATIVE_THRESHOLD = -0.20


def clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def score_to_state(
    score: float,
    *,
    positive_threshold: float = POSITIVE_THRESHOLD,
    negative_threshold: float = NEGATIVE_THRESHOLD,
) -> SignalState:
    if score >= positive_threshold:
        return "POSITIVE"
    if score <= negative_threshold:
        return "NEGATIVE"
    return "NEUTRAL"


def parse_as_of(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text[:10])


def parse_known_at(value: date | datetime | str | None) -> date | datetime | None:
    if value is None:
        return None
    if isinstance(value, date | datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    return date.fromisoformat(text[:10])


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def pit_allows(as_of: date, known_at: date | datetime | str | None) -> bool:
    return known_at_allows(as_of, parse_known_at(known_at))


def weighted_mean(parts: list[tuple[float, float]]) -> float | None:
    """parts = [(weight, value), ...]. Returns None when empty."""
    usable = [(w, v) for w, v in parts if w > 0]
    if not usable:
        return None
    w_sum = sum(w for w, _ in usable)
    if w_sum <= 0:
        return None
    return sum(w * v for w, v in usable) / w_sum
