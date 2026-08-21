"""Incremental date-range helpers."""

from __future__ import annotations

from datetime import date, timedelta


def compute_incremental_range(
    *,
    last_timestamp_date: date | None,
    default_from: date,
    today: date,
) -> tuple[date, date] | None:
    """Return inclusive [from, to] for missing data, or None if already up to date."""
    if last_timestamp_date is None:
        if default_from > today:
            return None
        return default_from, today
    start = last_timestamp_date + timedelta(days=1)
    if start > today:
        return None
    return start, today
