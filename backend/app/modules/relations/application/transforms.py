"""Point-in-time transforms for relation series inputs (no silent change forward-fill)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.modules.analytics.application.alignment import DatedValue, align_market_to_sparse_series


def asof_level_then_change(
    market_calendar: Iterable[date],
    series_levels: Iterable[DatedValue],
    *,
    mode: str,
) -> list[DatedValue]:
    """As-of align levels to market calendar, then difference consecutive levels.

    mode:
      - absolute_change: level[t] - level[t-1]
      - pct_change: (level[t] - level[t-1]) / level[t-1]

    Does NOT forward-fill the previous change value. When the as-of level is unchanged,
    the change is 0 (absolute) or 0.0 (pct). Missing prior as-of → no observation.
    """
    market_points = [DatedValue(date=d, value=0.0) for d in sorted(set(market_calendar))]
    aligned = align_market_to_sparse_series(market_points, series_levels)
    result: list[DatedValue] = []
    prev_level: float | None = None
    for row in aligned:
        level = row.right
        if level is None:
            prev_level = None
            continue
        if prev_level is None:
            prev_level = level
            continue
        if mode == "pct_change":
            if prev_level == 0:
                prev_level = level
                continue
            change = (level - prev_level) / prev_level
        else:
            change = level - prev_level
        result.append(DatedValue(date=row.date, value=float(change)))
        prev_level = level
    return result
