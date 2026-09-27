"""Market EOD gap detection + multi-day recovery contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.market.application.eod_gap import (
    MARKET_CURRENT,
    MARKET_STALE,
    detect_market_eod_gap,
    expected_completed_equity_session,
    trading_sessions_between,
)
from app.modules.market.application.eod_recovery import (
    MARKET_BACKFILL_NOOP,
    MARKET_BACKFILL_SUCCESS,
    run_eod_market_recovery,
)
from app.modules.market.domain.trading_calendar import MoexEquityTradingCalendar


def test_expected_session_skips_weekend() -> None:
    cal = MoexEquityTradingCalendar(day_off=None)
    # Sunday 2026-09-27 → previous trading day Friday 2026-09-25
    now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    assert expected_completed_equity_session(now=now, calendar=cal) == date(2026, 9, 25)


def test_trading_sessions_between_ignores_weekend() -> None:
    cal = MoexEquityTradingCalendar(day_off=None)
    sessions = trading_sessions_between(date(2026, 9, 10), date(2026, 9, 15), calendar=cal)
    assert date(2026, 9, 12) not in sessions  # Saturday
    assert date(2026, 9, 13) not in sessions  # Sunday
    assert date(2026, 9, 11) in sessions
    assert date(2026, 9, 14) in sessions
    assert date(2026, 9, 15) in sessions


def test_detect_gap_10_to_25() -> None:
    cal = MoexEquityTradingCalendar(day_off=None)
    session = MagicMock()
    complete = SimpleNamespace(
        as_of=date(2026, 9, 10),
        complete=True,
        to_dict=lambda: {"as_of": "2026-09-10"},
    )
    with (
        patch(
            "app.modules.market.application.eod_gap.latest_raw_market_date",
            return_value=date(2026, 9, 10),
        ),
        patch(
            "app.modules.market.application.eod_gap.select_latest_complete_as_of",
            return_value=complete,
        ),
    ):
        gap = detect_market_eod_gap(
            session,
            now=datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
            calendar=cal,
        )
    assert gap.status == MARKET_STALE
    assert gap.expected_completed_session == date(2026, 9, 25)
    assert gap.missing_count >= 10
    assert date(2026, 9, 11) in gap.missing_trading_sessions
    assert date(2026, 9, 25) in gap.missing_trading_sessions
    assert date(2026, 9, 12) not in gap.missing_trading_sessions


def test_detect_current_is_noop() -> None:
    cal = MoexEquityTradingCalendar(day_off=None)
    session = MagicMock()
    complete = SimpleNamespace(as_of=date(2026, 9, 25), complete=True, to_dict=lambda: {})
    with (
        patch(
            "app.modules.market.application.eod_gap.latest_raw_market_date",
            return_value=date(2026, 9, 25),
        ),
        patch(
            "app.modules.market.application.eod_gap.select_latest_complete_as_of",
            return_value=complete,
        ),
    ):
        gap = detect_market_eod_gap(
            session,
            now=datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
            calendar=cal,
        )
    assert gap.status == MARKET_CURRENT
    assert gap.missing_count == 0


def test_recovery_anchors_on_complete_not_raw_max() -> None:
    """Partial instrument ahead (raw max) must not skip universe backfill."""
    session = MagicMock()
    before = SimpleNamespace(
        status=MARKET_STALE,
        local_raw_max=date(2026, 9, 25),  # e.g. only SBER probed
        local_complete_eod=date(2026, 9, 10),
        expected_completed_session=date(2026, 9, 25),
        missing_trading_sessions=[date(2026, 9, 11), date(2026, 9, 25)],
        to_dict=lambda: {"status": MARKET_STALE},
    )
    after = SimpleNamespace(
        status=MARKET_CURRENT,
        local_raw_max=date(2026, 9, 25),
        local_complete_eod=date(2026, 9, 25),
        expected_completed_session=date(2026, 9, 25),
        missing_trading_sessions=[],
        to_dict=lambda: {"status": MARKET_CURRENT},
    )
    svc = MagicMock()
    svc.run_backfill.return_value = {
        "workflow_id": 1,
        "status": "SUCCESS",
        "stats": {"received": 100, "inserted": 100, "updated": 0},
    }
    complete = SimpleNamespace(complete=True, as_of=date(2026, 9, 25), to_dict=lambda: {})

    with (
        patch(
            "app.modules.market.application.eod_recovery.detect_market_eod_gap",
            side_effect=[before, after],
        ),
        patch(
            "app.modules.market.application.eod_recovery.instruments_with_moex_history",
            return_value=[SimpleNamespace(symbol="SBER"), SimpleNamespace(symbol="GAZP")],
        ),
        patch(
            "app.modules.market.application.eod_recovery.MarketIngestionService",
            return_value=svc,
        ),
        patch(
            "app.modules.market.application.eod_recovery.select_latest_complete_as_of",
            return_value=complete,
        ),
        patch(
            "app.modules.market.application.eod_gap.trading_sessions_between",
            return_value=[date(2026, 9, 11), date(2026, 9, 25)],
        ),
    ):
        out = run_eod_market_recovery(session)

    assert out["status"] == MARKET_BACKFILL_SUCCESS
    kwargs = svc.run_backfill.call_args.kwargs
    assert kwargs["date_from"] == date(2026, 9, 11)
    assert kwargs["date_to"] == date(2026, 9, 25)


def test_recovery_calls_multi_day_backfill_not_one_day() -> None:
    session = MagicMock()
    before = SimpleNamespace(
        status=MARKET_STALE,
        local_raw_max=date(2026, 9, 10),
        local_complete_eod=date(2026, 9, 10),
        expected_completed_session=date(2026, 9, 25),
        missing_trading_sessions=[date(2026, 9, 11), date(2026, 9, 25)],
        to_dict=lambda: {"status": MARKET_STALE},
    )
    after = SimpleNamespace(
        status=MARKET_CURRENT,
        local_raw_max=date(2026, 9, 25),
        local_complete_eod=date(2026, 9, 25),
        expected_completed_session=date(2026, 9, 25),
        missing_trading_sessions=[],
        to_dict=lambda: {"status": MARKET_CURRENT},
    )
    svc = MagicMock()
    svc.run_backfill.return_value = {
        "workflow_id": 1,
        "status": "SUCCESS",
        "stats": {"received": 100, "inserted": 100, "updated": 0},
    }
    complete = SimpleNamespace(complete=True, as_of=date(2026, 9, 25), to_dict=lambda: {})

    with (
        patch(
            "app.modules.market.application.eod_recovery.detect_market_eod_gap",
            side_effect=[before, after],
        ),
        patch(
            "app.modules.market.application.eod_recovery.instruments_with_moex_history",
            return_value=[SimpleNamespace(symbol="SBER"), SimpleNamespace(symbol="GAZP")],
        ),
        patch(
            "app.modules.market.application.eod_recovery.MarketIngestionService",
            return_value=svc,
        ),
        patch(
            "app.modules.market.application.eod_recovery.select_latest_complete_as_of",
            return_value=complete,
        ),
        patch(
            "app.modules.market.application.eod_gap.trading_sessions_between",
            return_value=[date(2026, 9, 11), date(2026, 9, 25)],
        ),
    ):
        out = run_eod_market_recovery(session)

    assert out["status"] == MARKET_BACKFILL_SUCCESS
    svc.run_backfill.assert_called_once()
    kwargs = svc.run_backfill.call_args.kwargs
    assert kwargs["date_from"] == date(2026, 9, 11)
    assert kwargs["date_to"] == date(2026, 9, 25)
    assert "SBER" in kwargs["symbols"]


def test_recovery_noop_when_current() -> None:
    session = MagicMock()
    current = SimpleNamespace(
        status=MARKET_CURRENT,
        to_dict=lambda: {"status": MARKET_CURRENT},
    )
    with patch(
        "app.modules.market.application.eod_recovery.detect_market_eod_gap",
        return_value=current,
    ):
        out = run_eod_market_recovery(session)
    assert out["status"] == MARKET_BACKFILL_NOOP
