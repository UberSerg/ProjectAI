"""Lukoil IR XLSX + multi-issuer catalog + entitlement calendar tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.modules.fundamentals.application.entitlement import derive_ex_date, entitlement_readiness
from app.modules.fundamentals.domain.types import (
    KNOWN_AT_QUALITY_MEETING_DATE_PROXY,
    KNOWN_AT_QUALITY_RECORD_DATE_PROXY,
    DividendStatus,
)
from app.modules.fundamentals.infrastructure.issuer_ir_xlsx_dividend_provider import (
    DEFAULT_ISSUER_IR_CATALOG,
    IssuerIrXlsxDividendProvider,
)
from app.modules.fundamentals.infrastructure.lukoil_ir_xlsx import (
    parse_lukoil_amount,
    parse_lukoil_declared_sheet,
)
from app.modules.market.domain.trading_calendar import MoexEquityTradingCalendar
from app.modules.market.infrastructure.ru_trading_calendar import get_moex_equity_trading_calendar

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LKOH_XLSX = FIXTURES / "lukoil_dividends_declared_sample.xlsx"
MAGNIT_DATES = FIXTURES / "magnit_dividends_dates_sample.xlsx"
MAGNIT_HISTORY = FIXTURES / "magnit_dividends_history_sample.xlsx"


def test_catalog_includes_mgnt_and_lkoh() -> None:
    secids = {s.secid for s in DEFAULT_ISSUER_IR_CATALOG}
    assert secids >= {"MGNT", "LKOH"}


def test_parse_lukoil_amount_common_vs_preferred() -> None:
    assert parse_lukoil_amount("278 ао") == (278.0, "common")
    assert parse_lukoil_amount("10 ап") == (10.0, "preferred")
    assert parse_lukoil_amount("0 ао") == (None, None)


def test_lukoil_fixture_events_and_known_at_quality() -> None:
    assert LKOH_XLSX.is_file()
    provider = IssuerIrXlsxDividendProvider(
        issuer_id_by_secid={"LKOH": 9},
        instrument_id_by_secid={"LKOH": 99},
        local_files={"LKOH": (LKOH_XLSX, LKOH_XLSX)},
    )
    events = list(provider.fetch_by_secid("LKOH"))
    assert events
    # preferred row must not appear
    assert all(e.metadata.get("share_class") == "common" for e in events)
    assert all(e.status == DividendStatus.APPROVED for e in events)
    qualities = {e.metadata["known_at_quality"] for e in events}
    assert KNOWN_AT_QUALITY_RECORD_DATE_PROXY in qualities or KNOWN_AT_QUALITY_MEETING_DATE_PROXY in qualities
    agm = [e for e in events if e.metadata.get("known_at_quality") == KNOWN_AT_QUALITY_MEETING_DATE_PROXY]
    if agm:
        assert agm[0].known_at == date(2022, 12, 5)
        assert agm[0].shareholder_approval_date == date(2022, 12, 5)


def test_lukoil_skips_preferred_when_common_expected() -> None:
    payload = LKOH_XLSX.read_bytes()
    rows = parse_lukoil_declared_sheet(payload, expected_share_class="common")
    assert all(r["share_class"] == "common" for r in rows)


def test_multi_issuer_local_catalog() -> None:
    provider = IssuerIrXlsxDividendProvider(
        local_files={
            "MGNT": (MAGNIT_DATES, MAGNIT_HISTORY),
            "LKOH": (LKOH_XLSX, LKOH_XLSX),
        },
        issuer_id_by_secid={"MGNT": 1, "LKOH": 2},
        instrument_id_by_secid={"MGNT": 10, "LKOH": 20},
    )
    mgnt = list(provider.fetch_by_secid("MGNT"))
    lkoh = list(provider.fetch_by_secid("LKOH"))
    assert mgnt and lkoh
    assert provider.readiness()["bounded_secids"] == ["LKOH", "MGNT"]


def test_trading_calendar_ru_workday_still_available() -> None:
    cal = get_moex_equity_trading_calendar()
    assert cal.is_trading_day(date(2024, 1, 6)) is False  # Saturday
    # RU production marks early Jan holidays; MOEX session calendar may differ.
    assert cal.coverage()["quality"] == "DERIVED_FROM_RU_PRODUCTION_CALENDAR"


def test_entitlement_t1_with_moex_session_calendar() -> None:
    # record Monday 2024-07-15 → T+1 → Fri 2024-07-12
    result = derive_ex_date(date(2024, 7, 15))
    assert result.ex_date == date(2024, 7, 12)
    assert result.settlement_cycle == "T+1"
    assert result.quality == "DERIVED_FROM_MOEX_ISS_HISTORY_SESSIONS"
    assert result.last_eligible_trading_date == date(2024, 7, 11)
    assert "OFFICIAL" not in result.quality


def test_entitlement_quality_never_claims_official_calendar_label() -> None:
    result = derive_ex_date(date(2024, 7, 15))
    ready = entitlement_readiness()
    assert "OFFICIAL" not in result.quality
    assert "OFFICIAL" not in str(ready["quality"])
    assert result.quality == "DERIVED_FROM_MOEX_ISS_HISTORY_SESSIONS"
    assert "MOEX ISS" in str(ready.get("calendar", {}).get("source", ""))


def test_entitlement_t2_historical() -> None:
    result = derive_ex_date(date(2023, 5, 10))
    assert result.settlement_cycle == "T+2"
    assert result.ex_date is not None
    assert result.ex_date < date(2023, 5, 10)
    assert result.quality == "DERIVED_FROM_MOEX_ISS_HISTORY_SESSIONS"
    ready = entitlement_readiness()
    assert ready["status"] == "PARTIAL"
    assert ready["settlement"]["t1_effective_from"] == "2023-07-31"


def test_moex_session_calendar_traded_jan_3_2024() -> None:
    from app.modules.market.infrastructure.moex_session_calendar import (
        get_moex_iss_history_session_calendar,
    )

    cal = get_moex_iss_history_session_calendar()
    assert cal.is_trading_day(date(2024, 1, 1)) is False
    assert cal.is_trading_day(date(2024, 1, 3)) is True
    assert cal.next_trading_day(date(2024, 1, 1)) == date(2024, 1, 3)


def test_weekends_only_calendar_quality() -> None:
    cal = MoexEquityTradingCalendar(day_off=None)
    assert cal.coverage()["quality"] == "WEEKENDS_ONLY_APPROXIMATE"
    assert cal.is_trading_day(date(2024, 7, 12)) is True
    assert cal.is_trading_day(date(2024, 7, 13)) is False


def test_lifecycle_recommendation_then_approval_revision() -> None:
    from app.modules.fundamentals.application.dividend_known_at import (
        synthetic_recommendation_then_approval_revision,
    )
    from app.modules.fundamentals.domain.types import DividendStatus

    events = synthetic_recommendation_then_approval_revision()
    assert events[0].status == DividendStatus.RECOMMENDED
    assert events[0].amount_per_share == 100.0
    assert events[1].status == DividendStatus.APPROVED
    assert events[1].amount_per_share == 80.0
    assert events[0].known_at < events[1].known_at
