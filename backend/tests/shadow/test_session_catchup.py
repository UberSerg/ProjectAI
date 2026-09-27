"""Shadow deterministic session catch-up — gap / resume / idempotency matrix."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.shadow.application.session_catchup import (
    CATCH_UP_BLOCKED,
    CATCH_UP_NO_OP,
    CATCH_UP_PARTIAL,
    CATCH_UP_SUCCESS,
    REASON_ALREADY_CURRENT,
    REASON_MISSING_MARKET_DATA,
    build_portfolio_catchup_plan,
    missing_sessions_for_watermark,
    run_portfolio_session_catchup,
)


def test_case1_no_missing_sessions_is_noop() -> None:
    session = MagicMock()
    with patch(
        "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
        return_value=[],
    ):
        missing = missing_sessions_for_watermark(
            session,
            last_processed=date(2026, 9, 10),
            latest_completed=date(2026, 9, 10),
        )
    assert missing == []


def test_case2_one_missing_session() -> None:
    session = MagicMock()
    with patch(
        "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
        return_value=[date(2026, 9, 11)],
    ):
        missing = missing_sessions_for_watermark(
            session,
            last_processed=date(2026, 9, 10),
            latest_completed=date(2026, 9, 11),
        )
    assert missing == [date(2026, 9, 11)]


def test_case3_calendar_gap_only_real_sessions() -> None:
    """10 calendar days → only observed candle sessions, ascending."""
    session = MagicMock()
    # Fri Sep 11 … Mon Sep 14 … Fri Sep 18 (weekends absent)
    observed = [
        date(2026, 9, 11),
        date(2026, 9, 14),
        date(2026, 9, 15),
        date(2026, 9, 16),
        date(2026, 9, 17),
        date(2026, 9, 18),
    ]
    with patch(
        "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
        return_value=observed,
    ):
        missing = missing_sessions_for_watermark(
            session,
            last_processed=date(2026, 9, 10),
            latest_completed=date(2026, 9, 18),
        )
    assert missing == observed
    assert date(2026, 9, 12) not in missing  # Saturday
    assert date(2026, 9, 13) not in missing  # Sunday
    assert missing == sorted(missing)


def test_case4_weekend_not_fabricated() -> None:
    with patch(
        "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
        return_value=[date(2026, 9, 14)],
    ):
        plan = build_portfolio_catchup_plan(
            MagicMock(),
            SimpleNamespace(id=1, last_processed_market_date=date(2026, 9, 11)),
            SimpleNamespace(name="A"),
            latest_completed=date(2026, 9, 14),
        )
    assert plan.missing_sessions == [date(2026, 9, 14)]
    assert plan.backlog_count == 1
    assert date(2026, 9, 12) not in plan.missing_sessions
    assert date(2026, 9, 13) not in plan.missing_sessions


def test_case6_missing_eod_blocks() -> None:
    """Gap vs complete EOD but no candle sessions → CATCH_UP_BLOCKED."""
    with patch(
        "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
        return_value=[],
    ):
        plan = build_portfolio_catchup_plan(
            MagicMock(),
            SimpleNamespace(id=1, last_processed_market_date=date(2026, 9, 10)),
            SimpleNamespace(name="A"),
            latest_completed=date(2026, 9, 16),
        )
    assert plan.status == CATCH_UP_BLOCKED
    assert plan.reason == REASON_MISSING_MARKET_DATA
    assert plan.blocking_session == date(2026, 9, 11)


def test_case9_already_current_noop() -> None:
    with patch(
        "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
        return_value=[],
    ):
        plan = build_portfolio_catchup_plan(
            MagicMock(),
            SimpleNamespace(id=1, last_processed_market_date=date(2026, 9, 16)),
            SimpleNamespace(name="A"),
            latest_completed=date(2026, 9, 16),
        )
    assert plan.status == CATCH_UP_NO_OP
    assert plan.reason == REASON_ALREADY_CURRENT


def test_run_catchup_processes_sessions_in_order() -> None:
    session = MagicMock()
    portfolio = SimpleNamespace(
        id=7,
        spec_id=1,
        last_processed_market_date=date(2026, 9, 10),
        activated_at=None,
        status="ACTIVE",
        last_decision_id=None,
    )
    spec = SimpleNamespace(id=1, name="SHADOW_A", candidate_config_hash="x")
    session.get.side_effect = lambda model, pk: {
        7: portfolio,
        1: spec,
    }.get(pk)

    days = [date(2026, 9, 11), date(2026, 9, 14), date(2026, 9, 15)]
    processed: list[date] = []

    def _process(_s, p, _spec, day, *, now):  # noqa: ANN001
        processed.append(day)
        p.last_processed_market_date = day
        return {"day": day.isoformat(), "skipped": None, "fills": 0}

    readiness = SimpleNamespace(
        latest_complete_eod_date=date(2026, 9, 15),
        to_dict=lambda: {},
    )

    with (
        patch(
            "app.modules.shadow.application.session_catchup.evaluate_eod_readiness",
            return_value=readiness,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
            side_effect=lambda _s, after: [d for d in days if after is None or d > after],
        ),
        patch(
            "app.modules.shadow.application.session_catchup.session_has_eod_candles",
            return_value=True,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.apply_pending_forward_decisions",
            return_value=0,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.process_shadow_market_day",
            side_effect=_process,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.refresh_shadow_portfolio_status",
        ),
        patch(
            "app.modules.shadow.application.session_catchup.ensure_market_data_for_catchup",
            return_value={"ok": True},
        ),
    ):
        out = run_portfolio_session_catchup(session, 7, ensure_market=True)

    assert out["status"] == CATCH_UP_SUCCESS
    assert processed == days
    assert out["sessions_replayed_dates"] == [d.isoformat() for d in days]


def test_case5_crash_resume_continues_without_duplicate_days() -> None:
    """Simulate resume after 3 sessions: only remaining days processed."""
    session = MagicMock()
    portfolio = SimpleNamespace(
        id=7,
        spec_id=1,
        last_processed_market_date=date(2026, 9, 15),  # already did 11,14,15
        activated_at=None,
        status="ACTIVE",
        last_decision_id=None,
    )
    spec = SimpleNamespace(id=1, name="SHADOW_A", candidate_config_hash="x")
    session.get.side_effect = lambda model, pk: {7: portfolio, 1: spec}.get(pk)

    all_days = [
        date(2026, 9, 11),
        date(2026, 9, 14),
        date(2026, 9, 15),
        date(2026, 9, 16),
        date(2026, 9, 17),
    ]
    processed: list[date] = []

    def _process(_s, p, _spec, day, *, now):  # noqa: ANN001
        processed.append(day)
        p.last_processed_market_date = day
        return {"day": day.isoformat(), "skipped": None, "fills": 0}

    readiness = SimpleNamespace(latest_complete_eod_date=date(2026, 9, 17), to_dict=lambda: {})

    with (
        patch(
            "app.modules.shadow.application.session_catchup.evaluate_eod_readiness",
            return_value=readiness,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
            side_effect=lambda _s, after: [d for d in all_days if after is None or d > after],
        ),
        patch(
            "app.modules.shadow.application.session_catchup.session_has_eod_candles",
            return_value=True,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.apply_pending_forward_decisions",
            return_value=0,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.process_shadow_market_day",
            side_effect=_process,
        ),
        patch("app.modules.shadow.application.session_catchup.refresh_shadow_portfolio_status"),
        patch(
            "app.modules.shadow.application.session_catchup.ensure_market_data_for_catchup",
            return_value={},
        ),
    ):
        out = run_portfolio_session_catchup(session, 7, ensure_market=False)

    assert processed == [date(2026, 9, 16), date(2026, 9, 17)]
    assert out["status"] == CATCH_UP_SUCCESS


def test_case6_mid_range_missing_candle_stops() -> None:
    session = MagicMock()
    portfolio = SimpleNamespace(
        id=7,
        spec_id=1,
        last_processed_market_date=date(2026, 9, 10),
        activated_at=None,
        status="ACTIVE",
        last_decision_id=None,
    )
    spec = SimpleNamespace(id=1, name="SHADOW_A", candidate_config_hash="x")
    session.get.side_effect = lambda model, pk: {7: portfolio, 1: spec}.get(pk)
    days = [date(2026, 9, 11), date(2026, 9, 14), date(2026, 9, 15)]
    processed: list[date] = []

    def _has_candle(_s, day):  # noqa: ANN001
        return day != date(2026, 9, 14)

    def _process(_s, p, _spec, day, *, now):  # noqa: ANN001
        processed.append(day)
        p.last_processed_market_date = day
        return {"day": day.isoformat(), "skipped": None, "fills": 0}

    readiness = SimpleNamespace(latest_complete_eod_date=date(2026, 9, 15), to_dict=lambda: {})

    with (
        patch(
            "app.modules.shadow.application.session_catchup.evaluate_eod_readiness",
            return_value=readiness,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
            side_effect=lambda _s, after: [d for d in days if after is None or d > after],
        ),
        patch(
            "app.modules.shadow.application.session_catchup.session_has_eod_candles",
            side_effect=_has_candle,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.apply_pending_forward_decisions",
            return_value=0,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.process_shadow_market_day",
            side_effect=_process,
        ),
        patch("app.modules.shadow.application.session_catchup.refresh_shadow_portfolio_status"),
        patch(
            "app.modules.shadow.application.session_catchup.ensure_market_data_for_catchup",
            return_value={},
        ),
    ):
        out = run_portfolio_session_catchup(session, 7, ensure_market=False)

    assert processed == [date(2026, 9, 11)]
    assert out["status"] == CATCH_UP_BLOCKED
    assert out["blocking_session"] == "2026-09-14"
    assert out["reason"] == REASON_MISSING_MARKET_DATA
    assert date(2026, 9, 15) not in processed


def test_case7_resume_after_data_available() -> None:
    """After unblock, catch-up continues from watermark (partial → success)."""
    session = MagicMock()
    portfolio = SimpleNamespace(
        id=7,
        spec_id=1,
        last_processed_market_date=date(2026, 9, 11),
        activated_at=None,
        status="ACTIVE",
        last_decision_id=None,
    )
    spec = SimpleNamespace(id=1, name="SHADOW_A", candidate_config_hash="x")
    session.get.side_effect = lambda model, pk: {7: portfolio, 1: spec}.get(pk)
    days = [date(2026, 9, 14), date(2026, 9, 15)]
    processed: list[date] = []

    def _process(_s, p, _spec, day, *, now):  # noqa: ANN001
        processed.append(day)
        p.last_processed_market_date = day
        return {"day": day.isoformat(), "skipped": None, "fills": 0}

    readiness = SimpleNamespace(latest_complete_eod_date=date(2026, 9, 15), to_dict=lambda: {})

    with (
        patch(
            "app.modules.shadow.application.session_catchup.evaluate_eod_readiness",
            return_value=readiness,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
            side_effect=lambda _s, after: [d for d in days if after is None or d > after],
        ),
        patch(
            "app.modules.shadow.application.session_catchup.session_has_eod_candles",
            return_value=True,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.apply_pending_forward_decisions",
            return_value=0,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.process_shadow_market_day",
            side_effect=_process,
        ),
        patch("app.modules.shadow.application.session_catchup.refresh_shadow_portfolio_status"),
        patch(
            "app.modules.shadow.application.session_catchup.ensure_market_data_for_catchup",
            return_value={},
        ),
    ):
        out = run_portfolio_session_catchup(session, 7, ensure_market=True)

    assert out["status"] == CATCH_UP_SUCCESS
    assert processed == days


def test_repeated_complete_catchup_noop() -> None:
    session = MagicMock()
    portfolio = SimpleNamespace(
        id=7,
        spec_id=1,
        last_processed_market_date=date(2026, 9, 18),
        activated_at=None,
        status="ACTIVE",
        last_decision_id=1,
    )
    spec = SimpleNamespace(id=1, name="SHADOW_A", candidate_config_hash="x")
    session.get.side_effect = lambda model, pk: {7: portfolio, 1: spec}.get(pk)
    readiness = SimpleNamespace(latest_complete_eod_date=date(2026, 9, 18), to_dict=lambda: {})

    with (
        patch(
            "app.modules.shadow.application.session_catchup.evaluate_eod_readiness",
            return_value=readiness,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
            return_value=[],
        ),
        patch(
            "app.modules.shadow.application.session_catchup.ensure_market_data_for_catchup",
            return_value={},
        ),
        patch(
            "app.modules.shadow.application.session_catchup.process_shadow_market_day",
        ) as process_day,
    ):
        out = run_portfolio_session_catchup(session, 7, ensure_market=False)

    assert out["status"] == CATCH_UP_NO_OP
    process_day.assert_not_called()


def test_max_sessions_partial() -> None:
    session = MagicMock()
    portfolio = SimpleNamespace(
        id=7,
        spec_id=1,
        last_processed_market_date=date(2026, 9, 10),
        activated_at=None,
        status="ACTIVE",
        last_decision_id=None,
    )
    spec = SimpleNamespace(id=1, name="SHADOW_A", candidate_config_hash="x")
    session.get.side_effect = lambda model, pk: {7: portfolio, 1: spec}.get(pk)
    days = [date(2026, 9, 11), date(2026, 9, 14), date(2026, 9, 15)]
    processed: list[date] = []

    def _process(_s, p, _spec, day, *, now):  # noqa: ANN001
        processed.append(day)
        p.last_processed_market_date = day
        return {"day": day.isoformat(), "skipped": None, "fills": 0}

    readiness = SimpleNamespace(latest_complete_eod_date=date(2026, 9, 15), to_dict=lambda: {})

    with (
        patch(
            "app.modules.shadow.application.session_catchup.evaluate_eod_readiness",
            return_value=readiness,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.list_trading_sessions_after",
            side_effect=lambda _s, after: [d for d in days if after is None or d > after],
        ),
        patch(
            "app.modules.shadow.application.session_catchup.session_has_eod_candles",
            return_value=True,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.apply_pending_forward_decisions",
            return_value=0,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.process_shadow_market_day",
            side_effect=_process,
        ),
        patch("app.modules.shadow.application.session_catchup.refresh_shadow_portfolio_status"),
        patch(
            "app.modules.shadow.application.session_catchup.ensure_market_data_for_catchup",
            return_value={},
        ),
    ):
        out = run_portfolio_session_catchup(session, 7, ensure_market=False, max_sessions=1)

    assert processed == [date(2026, 9, 11)]
    assert out["status"] == CATCH_UP_PARTIAL
    assert out["backlog_remaining"] == 2
