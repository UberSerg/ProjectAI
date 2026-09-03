"""Plan official candle fetches from proven source windows only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class PlannedSourceRange:
    instrument_id: int
    source_mapping_id: int | None
    external_id: str
    board: str
    valid_from: date
    valid_to: date | None
    effective_from: date
    effective_to: date


def _window_last_day(valid_to: date | None, requested_to: date) -> date:
    if valid_to is None:
        return requested_to
    return min(requested_to, valid_to - timedelta(days=1))


def plan_source_ranges(
    mappings: list[Any],
    requested_from: date,
    requested_to: date,
    *,
    instrument_id: int | None = None,
) -> list[PlannedSourceRange]:
    """Intersect requested inclusive dates with proven half-open mapping windows.

    proven window: valid_from <= t < valid_to (valid_to NULL = open-ended).
    valid_from NULL is start-unknown — never used for a historical fetch.
    Gaps between mappings are left as gaps. Current mapping is not a fallback.
    """
    if requested_from > requested_to:
        return []
    planned: list[PlannedSourceRange] = []
    for mapping in mappings:
        valid_from = mapping.valid_from
        if valid_from is None:
            continue
        last_day = _window_last_day(mapping.valid_to, requested_to)
        effective_from = max(valid_from, requested_from)
        effective_to = last_day
        if effective_from > effective_to:
            continue
        planned.append(
            PlannedSourceRange(
                instrument_id=instrument_id if instrument_id is not None else mapping.instrument_id,
                source_mapping_id=getattr(mapping, "id", None),
                external_id=mapping.external_id,
                board=(mapping.board or "").strip() or "TQBR",
                valid_from=valid_from,
                valid_to=mapping.valid_to,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        )
    planned.sort(key=lambda item: (item.effective_from, item.board))
    return planned


def missing_coverage_ranges(
    have_min: date | None,
    have_max: date | None,
    requested_from: date,
    requested_to: date,
) -> list[tuple[date, date]]:
    """Prefix/suffix holes only. Already-covered interiors are not re-requested."""
    if requested_from > requested_to:
        return []
    if have_min is None or have_max is None:
        return [(requested_from, requested_to)]
    ranges: list[tuple[date, date]] = []
    if have_min > requested_from:
        end = min(have_min - timedelta(days=1), requested_to)
        if end >= requested_from:
            ranges.append((requested_from, end))
    if have_max < requested_to:
        start = max(have_max + timedelta(days=1), requested_from)
        if start <= requested_to:
            ranges.append((start, requested_to))
    return ranges
