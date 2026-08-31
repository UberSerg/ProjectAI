"""Tests for series as-of then change transforms."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.analytics.application.alignment import DatedValue
from app.modules.relations.application.transforms import asof_level_then_change


def test_absolute_change_no_change_forward_fill() -> None:
    calendar = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    levels = [
        DatedValue(date=date(2024, 1, 1), value=16.0),
        DatedValue(date=date(2024, 1, 3), value=17.0),
    ]
    changed = asof_level_then_change(calendar, levels, mode="absolute_change")
    by_date = {p.date: p.value for p in changed}
    # Jan 2: as-of still 16 → change 0 (not forward-filled previous change)
    assert by_date[date(2024, 1, 2)] == 0.0
    # Jan 3: 17 - 16 = 1
    assert by_date[date(2024, 1, 3)] == 1.0
    # Jan 4: as-of still 17 → change 0
    assert by_date[date(2024, 1, 4)] == 0.0


def test_pct_change_asof() -> None:
    calendar = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    levels = [
        DatedValue(date=date(2024, 1, 1), value=100.0),
        DatedValue(date=date(2024, 1, 2), value=110.0),
    ]
    changed = asof_level_then_change(calendar, levels, mode="pct_change")
    by_date = {p.date: p.value for p in changed}
    assert by_date[date(2024, 1, 2)] == pytest.approx(0.1)
    assert by_date[date(2024, 1, 3)] == 0.0
