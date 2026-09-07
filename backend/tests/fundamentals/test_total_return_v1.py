"""Gross total return domain fixtures."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.fundamentals.domain.total_return import (
    DividendCashPoint,
    ReturnQuality,
    assess_dividend_coverage,
    compute_gross_total_return,
    compute_price_return,
)


def test_price_return_basic() -> None:
    assert compute_price_return(start_price=100.0, end_price=110.0) == pytest.approx(0.1)


def test_gross_total_return_with_dividend() -> None:
    # Price −10%, cash dividend +5 → gross −5%
    result = compute_gross_total_return(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        start_price=100.0,
        end_price=90.0,
        dividends=(
            DividendCashPoint(ex_date=date(2026, 5, 15), amount_per_share=5.0, currency="RUB"),
        ),
    )
    assert result.quality is ReturnQuality.READY
    assert result.price_return == pytest.approx(-0.1)
    assert result.dividend_cash == pytest.approx(5.0)
    assert result.total_return_gross == pytest.approx(-0.05)


def test_dividend_outside_window_ignored() -> None:
    result = compute_gross_total_return(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        start_price=100.0,
        end_price=100.0,
        dividends=(
            DividendCashPoint(ex_date=date(2025, 12, 15), amount_per_share=10.0),
            DividendCashPoint(ex_date=date(2026, 4, 1), amount_per_share=10.0),
        ),
    )
    assert result.dividend_cash == 0.0
    assert result.total_return_gross == pytest.approx(0.0)
    assert result.quality is ReturnQuality.READY


def test_missing_dividend_amount_is_partial() -> None:
    result = compute_gross_total_return(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        start_price=100.0,
        end_price=100.0,
        dividends=(DividendCashPoint(ex_date=date(2026, 2, 1), amount_per_share=None),),
    )
    assert result.quality is ReturnQuality.PARTIAL
    assert "dividend_amount_missing" in result.reasons
    assert result.price_return == pytest.approx(0.0)


def test_missing_prices_not_ready() -> None:
    result = compute_gross_total_return(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 1),
        start_price=None,
        end_price=100.0,
        dividends=(),
    )
    assert result.quality is ReturnQuality.NOT_READY


def test_coverage_empty_dividends_not_ready() -> None:
    report = assess_dividend_coverage(
        instruments_with_price_history=40,
        dividend_events_stored=0,
        instruments_with_dividend_events=0,
        accepted_provider=False,
    )
    assert report.quality is ReturnQuality.NOT_READY
    assert "no_accepted_dividend_provider" in report.reasons


def test_coverage_partial_and_ready() -> None:
    partial = assess_dividend_coverage(
        instruments_with_price_history=100,
        dividend_events_stored=20,
        instruments_with_dividend_events=20,
        accepted_provider=True,
    )
    assert partial.quality is ReturnQuality.PARTIAL

    ready = assess_dividend_coverage(
        instruments_with_price_history=100,
        dividend_events_stored=200,
        instruments_with_dividend_events=80,
        accepted_provider=True,
    )
    assert ready.quality is ReturnQuality.READY
