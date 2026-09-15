"""Gross total return foundation V2 — strict vs research mode."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.fundamentals.domain.total_return import (
    DividendCashPoint,
    ReturnQuality,
    compute_gross_total_return,
)


def test_gross_tr_no_dividend() -> None:
    r = compute_gross_total_return(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        start_price=100.0,
        end_price=110.0,
        dividends=(),
    )
    assert r.price_return == pytest.approx(0.1)
    assert r.dividend_cash == 0.0
    assert r.total_return_gross == pytest.approx(0.1)
    assert r.quality == ReturnQuality.READY


def test_gross_tr_one_dividend() -> None:
    r = compute_gross_total_return(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 6, 1),
        start_price=100.0,
        end_price=105.0,
        dividends=(DividendCashPoint(ex_date=date(2024, 3, 1), amount_per_share=5.0),),
    )
    assert r.dividend_cash == 5.0
    assert r.total_return_gross == pytest.approx(0.10)  # (5+5)/100
    assert r.quality == ReturnQuality.READY


def test_gross_tr_missing_amount_partial() -> None:
    r = compute_gross_total_return(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 6, 1),
        start_price=100.0,
        end_price=100.0,
        dividends=(DividendCashPoint(ex_date=date(2024, 3, 1), amount_per_share=None),),
    )
    assert r.quality == ReturnQuality.PARTIAL


def test_gross_tr_outside_window_ignored() -> None:
    r = compute_gross_total_return(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        start_price=100.0,
        end_price=100.0,
        dividends=(
            DividendCashPoint(ex_date=date(2023, 12, 15), amount_per_share=10.0),
            DividendCashPoint(ex_date=date(2024, 2, 2), amount_per_share=10.0),
        ),
    )
    assert r.dividends_considered == 0
    assert r.dividend_cash == 0.0
