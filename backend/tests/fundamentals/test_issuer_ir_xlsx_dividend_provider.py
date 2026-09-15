"""Issuer IR XLSX dividend provider + settlement ex-date helpers."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.modules.fundamentals.domain.settlement_ex_date import (
    MOEX_EQUITY_T1_EFFECTIVE,
    estimate_ex_date,
    settlement_lag_trading_days,
)
from app.modules.fundamentals.domain.types import (
    KNOWN_AT_QUALITY_APPROXIMATE_PUBLICATION_PROXY,
    SOURCE_ISSUER_IR_XLS_V1,
    DividendStatus,
)
from app.modules.fundamentals.infrastructure.issuer_ir_xlsx_dividend_provider import (
    IssuerIrXlsxDividendProvider,
    normalize_period_label,
    parse_russian_date,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DATES_XLSX = FIXTURES / "magnit_dividends_dates_sample.xlsx"
HISTORY_XLSX = FIXTURES / "magnit_dividends_history_sample.xlsx"


def test_normalize_period_labels() -> None:
    assert normalize_period_label("2023 за год").label() == "FY:2023"
    assert normalize_period_label("9М 2020").label() == "M9:2020"
    assert normalize_period_label("2020 9М").label() == "M9:2020"
    assert normalize_period_label("1П 2017").label() == "H1:2017"
    assert normalize_period_label("1Кв 2012").label() == "Q1:2012"
    assert normalize_period_label("2020 ИТОГ") is None


def test_parse_russian_date() -> None:
    assert parse_russian_date("31 мая 2024") == date(2024, 5, 31)
    assert parse_russian_date("27 июня 2024 ") == date(2024, 6, 27)
    assert parse_russian_date(None) is None


def test_magnit_fixture_join_statuses() -> None:
    provider = IssuerIrXlsxDividendProvider(
        issuer_id_by_secid={"MGNT": 42},
        instrument_id_by_secid={"MGNT": 7},
        local_files={"MGNT": (DATES_XLSX, HISTORY_XLSX)},
    )
    events = list(provider.fetch_by_secid("MGNT"))
    assert events
    by_period = {e.metadata["period_key"]: e for e in events}

    approved = by_period["FY:2023"]
    assert approved.status == DividendStatus.APPROVED
    assert approved.amount_per_share == pytest.approx(412.13)
    assert approved.record_date == date(2024, 7, 15)
    assert approved.shareholder_approval_date == date(2024, 6, 27)
    assert approved.known_at == date(2024, 6, 27)
    assert approved.currency == "RUB"
    assert approved.source == SOURCE_ISSUER_IR_XLS_V1
    assert approved.issuer_id == 42
    assert approved.instrument_id == 7
    assert approved.metadata["known_at_quality"] == KNOWN_AT_QUALITY_APPROXIMATE_PUBLICATION_PROXY
    assert approved.ex_date is None

    recommended = by_period["M9:2024"]
    assert recommended.status == DividendStatus.RECOMMENDED
    assert recommended.shareholder_approval_date is None
    assert recommended.known_at == date(2024, 10, 10)
    assert recommended.metadata["entitlement_eligible"] is False

    assert "FY:2008" not in by_period  # approved without amount skipped


def test_unknown_issuer_returns_empty() -> None:
    provider = IssuerIrXlsxDividendProvider(
        local_files={"MGNT": (DATES_XLSX, HISTORY_XLSX)},
        issuer_id_by_secid={"MGNT": 1},
    )
    assert provider.fetch_dividends(999) == ()


def test_settlement_lag_t2_then_t1() -> None:
    assert settlement_lag_trading_days(date(2023, 7, 30)) == 2
    assert settlement_lag_trading_days(MOEX_EQUITY_T1_EFFECTIVE) == 1
    assert settlement_lag_trading_days(date(2024, 1, 15)) == 1


def test_estimate_ex_date_weekends_only_approximate() -> None:
    # record Monday 2024-07-15 → T+1 → prior trading day Friday 2024-07-12
    ex, prov = estimate_ex_date(date(2024, 7, 15))
    assert ex == date(2024, 7, 12)
    assert prov["settlement_cycle"] == "T+1"
    assert prov["quality"] == "APPROXIMATE"

    # before T+1 effective: T+2
    ex2, prov2 = estimate_ex_date(date(2023, 7, 14))  # Friday
    # Fri -1 Thu -2 Wed
    assert ex2 == date(2023, 7, 12)
    assert prov2["settlement_cycle"] == "T+2"


def test_estimate_ex_date_with_calendar_partial() -> None:
    # Artificial calendar: only weekdays listed; treat Mon holiday.
    trading = {
        date(2024, 7, 10),
        date(2024, 7, 11),
        date(2024, 7, 12),
        # 2024-07-15 record; skip 2024-07-15 itself for subtraction walk
        date(2024, 7, 16),
    }
    ex, prov = estimate_ex_date(date(2024, 7, 15), calendar=trading)
    assert ex == date(2024, 7, 12)
    assert prov["quality"] == "PARTIAL"
