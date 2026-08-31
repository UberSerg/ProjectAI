"""Point-in-time alignment for temporal series (no correlation)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class DatedValue:
    date: date
    value: float


@dataclass(frozen=True, slots=True)
class AlignedRow:
    date: date
    left: float | None
    right: float | None


def align_market_to_market(left: Iterable[DatedValue], right: Iterable[DatedValue]) -> list[AlignedRow]:
    """Inner join on observation dates — no synthetic fill."""
    left_map = {item.date: item.value for item in left}
    right_map = {item.date: item.value for item in right}
    common = sorted(set(left_map) & set(right_map))
    return [AlignedRow(date=d, left=left_map[d], right=right_map[d]) for d in common]


def align_market_to_sparse_series(
    market: Iterable[DatedValue],
    series: Iterable[DatedValue],
) -> list[AlignedRow]:
    """As-of join: for each market date t use last series value with date <= t."""
    market_sorted = sorted(market, key=lambda item: item.date)
    series_sorted = sorted(series, key=lambda item: item.date)
    if not market_sorted:
        return []

    result: list[AlignedRow] = []
    series_idx = 0
    current: float | None = None
    series_len = len(series_sorted)

    for point in market_sorted:
        while series_idx < series_len and series_sorted[series_idx].date <= point.date:
            current = series_sorted[series_idx].value
            series_idx += 1
        result.append(AlignedRow(date=point.date, left=point.value, right=current))

    return result
