"""Tests for RelationsComputeService helpers / no-lookahead load boundary."""

from __future__ import annotations

from datetime import date

from app.modules.relations.application.compute import _iter_as_of_dates


def test_weekly_as_of_includes_fridays_and_end() -> None:
    dates = _iter_as_of_dates(date(2026, 1, 1), date(2026, 1, 31), "WEEKLY")
    assert date(2026, 1, 31) in dates
    assert all(d.weekday() == 4 or d == date(2026, 1, 31) for d in dates)


def test_daily_as_of_contiguous() -> None:
    dates = _iter_as_of_dates(date(2026, 1, 1), date(2026, 1, 5), "DAILY")
    assert dates == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 4),
        date(2026, 1, 5),
    ]
