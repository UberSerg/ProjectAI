"""Next execution session uses MOEX calendar and never presents a past day."""

from __future__ import annotations

from datetime import date

from app.modules.shadow.application.pipeline_status import next_session_date_from_eod


def test_friday_eod_to_monday_trading_day() -> None:
    # 2026-10-09 is Friday; next MOEX session is Monday 2026-10-12.
    assert next_session_date_from_eod(date(2026, 10, 9), today=date(2026, 10, 10)) == "2026-10-12"


def test_weekend_skipped() -> None:
    assert next_session_date_from_eod(date(2026, 10, 10), today=date(2026, 10, 11)) == "2026-10-12"


def test_stale_eod_does_not_invent_past_next_session() -> None:
    # EOD 13.10.2026 while wall clock is 28.10.2026 → backlog, not a fake «next».
    assert next_session_date_from_eod(date(2026, 10, 13), today=date(2026, 10, 28)) is None


def test_current_eod_returns_future_session() -> None:
    assert next_session_date_from_eod(date(2026, 10, 27), today=date(2026, 10, 28)) == "2026-10-28"


def test_none_eod() -> None:
    assert next_session_date_from_eod(None) is None
