"""Dividend Coverage V2 — NOT_READY provider + total return wiring tests."""

from __future__ import annotations

from datetime import date

from app.modules.fundamentals.application.dividend_provider import (
    NotReadyDividendProvider,
    get_dividend_provider,
)
from app.modules.fundamentals.domain.total_return import (
    DividendCashPoint,
    compute_gross_total_return,
)


def test_default_provider_not_ready() -> None:
    provider = get_dividend_provider()
    ready = provider.readiness()
    assert ready["status"] == "NOT_READY"
    assert ready["accepted"] is False
    assert provider.fetch_dividends("SBER") == ()


def test_not_ready_reasons_document_moex_rejection() -> None:
    reasons = NotReadyDividendProvider().readiness()["reasons"]
    joined = " ".join(reasons)
    assert "rejected" in joined or "moex" in joined.lower() or "provider" in joined


def test_total_return_without_dividends() -> None:
    result = compute_gross_total_return(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 1),
        start_price=100.0,
        end_price=110.0,
        dividends=(),
    )
    assert result.total_return_gross == 0.1
    assert result.dividend_cash == 0.0
    assert result.quality.value == "READY"


def test_total_return_with_dividends() -> None:
    result = compute_gross_total_return(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 1),
        start_price=100.0,
        end_price=100.0,
        dividends=(
            DividendCashPoint(ex_date=date(2026, 3, 1), amount_per_share=5.0, currency="RUB"),
        ),
    )
    assert result.total_return_gross == 0.05
    assert result.dividend_cash == 5.0
