"""Deterministic rebalance calendar helpers."""

from __future__ import annotations

from datetime import date


def isoweek_key(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return int(iso.year), int(iso.week)


def weekly_rebalance_dates(trading_days: list[date]) -> list[date]:
    """First available trading observation of each ISO calendar week.

    Monday need not exist — first session in the week is the rebalance day.
    """
    if not trading_days:
        return []
    ordered = sorted(trading_days)
    out: list[date] = []
    seen: set[tuple[int, int]] = set()
    for d in ordered:
        key = isoweek_key(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def next_trading_day(trading_days: list[date], d: date) -> date | None:
    ordered = sorted(trading_days)
    for day in ordered:
        if day > d:
            return day
    return None
