"""SPLIT-only corporate-action draft. Official MOEX splits feed has no known_at."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

EVENT_TYPE_SPLIT = "SPLIT"
EVENT_TYPE_REVERSE_SPLIT = "REVERSE_SPLIT"
SOURCE_MOEX = "MOEX"
MOEX_SPLITS_FEED = "iss/statistics/engines/stock/splits"

# Official ISS /iss/statistics/engines/stock/splits.json fields only.
MOEX_SPLIT_FIELDS = ("tradedate", "secid", "before", "after")
SPLIT_FEED_EVENT_TYPES = frozenset({EVENT_TYPE_SPLIT, EVENT_TYPE_REVERSE_SPLIT})


def split_adjustment_factor(before: Decimal, after: Decimal) -> Decimal:
    """Mechanical factor = after / before. Usable after effective_date, not as a PIT announcement."""
    if before <= 0 or after <= 0:
        raise ValueError("split before and after must be > 0")
    return after / before


def classify_split_factor(factor: Decimal) -> str | None:
    """Domain type from ratio. Source feed name is not the event type. No DENOMINATION_CHANGE heuristic."""
    if factor > 1:
        return EVENT_TYPE_SPLIT
    if factor > 0 and factor < 1:
        return EVENT_TYPE_REVERSE_SPLIT
    return None


@dataclass(frozen=True, slots=True)
class SplitEventDraft:
    """Normalized SPLIT draft. known_at is NULL when the official feed has no announcement time."""

    secid: str
    effective_date: date
    split_before: Decimal
    split_after: Decimal
    adjustment_factor: Decimal
    source: str = SOURCE_MOEX
    event_type: str = EVENT_TYPE_SPLIT
    known_at: datetime | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SplitParseResult:
    accepted: tuple[SplitEventDraft, ...]
    rejected: int
    received: int


def payload_for_split(draft: SplitEventDraft) -> dict[str, Any]:
    return {
        "split_before": str(draft.split_before),
        "split_after": str(draft.split_after),
        "adjustment_factor": str(draft.adjustment_factor),
        "secid": draft.secid,
        "raw": draft.raw or {},
        "source_feed": MOEX_SPLITS_FEED,
        "known_at_semantics": "absent_from_source",
    }


def validate_split_ratio(before: Decimal, after: Decimal) -> None:
    if before <= 0 or after <= 0:
        raise ValueError("split before and after must be > 0")
