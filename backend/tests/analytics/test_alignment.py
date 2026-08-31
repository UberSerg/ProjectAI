"""Point-in-time alignment tests."""

from __future__ import annotations

from datetime import date

from app.modules.analytics.application.alignment import (
    DatedValue,
    align_market_to_market,
    align_market_to_sparse_series,
)


def test_market_inner_join() -> None:
    left = [DatedValue(date(2024, 1, 1), 1.0), DatedValue(date(2024, 1, 3), 2.0)]
    right = [DatedValue(date(2024, 1, 1), 10.0), DatedValue(date(2024, 1, 2), 20.0)]
    rows = align_market_to_market(left, right)
    assert len(rows) == 1
    assert rows[0].date == date(2024, 1, 1)


def test_sparse_asof_no_future_leak() -> None:
    series = [DatedValue(date(2024, 1, 1), 10.0), DatedValue(date(2024, 1, 5), 20.0)]
    market = [
        DatedValue(date(2024, 1, 2), 1.0),
        DatedValue(date(2024, 1, 4), 1.0),
        DatedValue(date(2024, 1, 5), 1.0),
        DatedValue(date(2024, 1, 6), 1.0),
    ]
    rows = align_market_to_sparse_series(market, series)
    assert [r.right for r in rows] == [10.0, 10.0, 20.0, 20.0]
