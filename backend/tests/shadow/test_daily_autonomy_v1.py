"""Daily autonomy: session gates, pipeline status, catch-up orchestration."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.domain.ports.intraday_market import MarketSessionStatus, QuoteFreshness
from app.modules.shadow.application.daily_operations import (
    READY_NO_REBALANCE,
    STAGE_ALREADY_CURRENT,
    STAGE_DISABLED,
    STAGE_SUCCESS,
    STAGE_WAITING_INPUT,
    WAITING_FOR_ANALYTICS,
    evaluate_eod_readiness,
    maybe_startup_catchup,
    maybe_trigger_cycle_if_ready,
)
from app.modules.shadow.application.pipeline_status import (
    CURRENT_MID_SESSION_WAIT,
    build_pipeline_status,
    detect_mid_session_activation,
)
from app.modules.shadow.domain.open_execution import (
    REASON_ELIGIBLE,
    REASON_ORDER_CREATED_AFTER_OPEN,
    can_fill_with_session_open,
    session_open_time_utc,
)


def test_activation_after_open_no_fill_today() -> None:
    """V2 activated after OPEN → cannot fill at today's OPEN (prospective guard)."""
    session_day = date(2026, 9, 7)
    open_at = session_open_time_utc(session_day)
    created = datetime(2026, 9, 7, 13, 38, tzinfo=UTC)  # after 07:00 UTC
    assert created > open_at
    result = can_fill_with_session_open(
        order_created_at=created,
        min_execution_date=date(2026, 9, 8),
        session_date=session_day,
        open_price=100.0,
        market_status=MarketSessionStatus.OPEN,
        quote_freshness=QuoteFreshness.LIVE,
        observed_at=datetime(2026, 9, 7, 14, 0, tzinfo=UTC),
    )
    assert result.eligible is False
    assert result.reason in (REASON_ORDER_CREATED_AFTER_OPEN, "MIN_EXECUTION_DATE_NOT_REACHED")


def test_order_before_open_fill_ok() -> None:
    result = can_fill_with_session_open(
        order_created_at=datetime(2026, 9, 6, 18, 0, tzinfo=UTC),
        min_execution_date=date(2026, 9, 7),
        session_date=date(2026, 9, 7),
        open_price=101.5,
        market_status=MarketSessionStatus.OPEN,
        quote_freshness=QuoteFreshness.LIVE,
        observed_at=datetime(2026, 9, 7, 7, 5, tzinfo=UTC),
    )
    assert result.eligible is True
    assert result.reason == REASON_ELIGIBLE


def test_mid_session_activation_flag() -> None:
    session = MagicMock()
    portfolio = SimpleNamespace(
        activated_at=datetime(2026, 9, 7, 13, 38, tzinfo=UTC),
    )
    session.scalars.return_value.all.return_value = []
    mid, code = detect_mid_session_activation(
        session,
        now=datetime(2026, 9, 7, 14, 0, tzinfo=UTC),
        portfolios=[(portfolio, SimpleNamespace())],
    )
    assert mid is True
    assert code == CURRENT_MID_SESSION_WAIT


def test_waiting_analytics_then_catchup_triggers() -> None:
    session = MagicMock()
    eod = date(2026, 9, 4)
    readiness = SimpleNamespace(
        ready=False,
        blocker_code=WAITING_FOR_ANALYTICS,
        latest_complete_eod_date=eod,
        to_dict=lambda: {"ready": False, "blocker_code": WAITING_FOR_ANALYTICS},
    )
    wm = {
        "raw_market_latest_date": eod,
        "analytics_v2_latest_date": date(2026, 9, 3),
        "technical_v2_latest_date": date(2026, 9, 3),
        "forward_latest_as_of": date(2026, 9, 3),
    }
    settings = SimpleNamespace(
        eod_readiness_retry_enabled=True,
        research_live_mode=True,
    )
    mock_task = MagicMock()
    mock_task.delay.return_value = SimpleNamespace(id="task-1")

    with (
        patch(
            "app.modules.shadow.application.daily_operations.get_settings",
            return_value=settings,
        ),
        patch(
            "app.modules.shadow.application.daily_operations.evaluate_eod_readiness",
            return_value=readiness,
        ),
        patch(
            "app.modules.shadow.application.daily_operations._collect_watermarks",
            return_value=wm,
        ),
        patch(
            "app.modules.shadow.application.daily_operations._last_successful_cycle",
            return_value=None,
        ),
        patch(
            "app.modules.shadow.application.daily_operations._latest_cycle_workflow",
            return_value=None,
        ),
        patch("app.worker.tasks.daily_research_cycle", mock_task),
    ):
        out = maybe_trigger_cycle_if_ready(session)

    assert out["stage"] == STAGE_SUCCESS
    assert out["status"] == STAGE_SUCCESS
    assert out.get("triggered") is True
    mock_task.delay.assert_called_once()


def test_catchup_idempotent_already_current() -> None:
    session = MagicMock()
    eod = date(2026, 9, 4)
    readiness = SimpleNamespace(
        ready=True,
        blocker_code=None,
        latest_complete_eod_date=eod,
        to_dict=lambda: {"ready": True},
    )
    wm = {
        "raw_market_latest_date": eod,
        "analytics_v2_latest_date": eod,
        "technical_v2_latest_date": eod,
        "forward_latest_as_of": eod,
    }
    last_ok = SimpleNamespace(
        meta={"market_watermark_after": eod.isoformat()},
        finished_at=datetime(2026, 9, 4, 19, 0, tzinfo=UTC),
        updated_at=None,
    )
    settings = SimpleNamespace(eod_readiness_retry_enabled=True, research_live_mode=True)

    with (
        patch(
            "app.modules.shadow.application.daily_operations.get_settings",
            return_value=settings,
        ),
        patch(
            "app.modules.shadow.application.daily_operations.evaluate_eod_readiness",
            return_value=readiness,
        ),
        patch(
            "app.modules.shadow.application.daily_operations._collect_watermarks",
            return_value=wm,
        ),
        patch(
            "app.modules.shadow.application.daily_operations._last_successful_cycle",
            return_value=last_ok,
        ),
    ):
        first = maybe_trigger_cycle_if_ready(session)
        second = maybe_trigger_cycle_if_ready(session)

    assert first["stage"] == STAGE_ALREADY_CURRENT
    assert second["stage"] == STAGE_ALREADY_CURRENT


def test_catchup_disabled_without_retry_flag() -> None:
    session = MagicMock()
    settings = SimpleNamespace(eod_readiness_retry_enabled=False, research_live_mode=False)
    with patch(
        "app.modules.shadow.application.daily_operations.get_settings",
        return_value=settings,
    ):
        out = maybe_trigger_cycle_if_ready(session)
    assert out["stage"] == STAGE_DISABLED


def test_waiting_input_when_market_incomplete() -> None:
    session = MagicMock()
    readiness = SimpleNamespace(
        ready=False,
        blocker_code="WAITING_FOR_MARKET_COMPLETE",
        latest_complete_eod_date=None,
        to_dict=lambda: {"ready": False},
    )
    settings = SimpleNamespace(eod_readiness_retry_enabled=True, research_live_mode=True)
    with (
        patch(
            "app.modules.shadow.application.daily_operations.get_settings",
            return_value=settings,
        ),
        patch(
            "app.modules.shadow.application.daily_operations.evaluate_eod_readiness",
            return_value=readiness,
        ),
        patch(
            "app.modules.shadow.application.daily_operations._collect_watermarks",
            return_value={},
        ),
    ):
        out = maybe_trigger_cycle_if_ready(session)
    assert out["stage"] == STAGE_WAITING_INPUT


def test_ready_no_rebalance_pipeline_status() -> None:
    session = MagicMock()
    session.scalar.return_value = date(2026, 9, 4)
    readiness = SimpleNamespace(
        ready=True,
        blocker_code=None,
        latest_complete_eod_date=date(2026, 9, 4),
    )
    wm = {
        "raw_market_latest_date": date(2026, 9, 4),
        "analytics_v2_latest_date": date(2026, 9, 4),
        "technical_v2_latest_date": date(2026, 9, 4),
        "relations_v2_latest_as_of": date(2026, 9, 1),
        "forward_latest_as_of": date(2026, 9, 4),
    }
    settings = SimpleNamespace(
        research_live_mode=True,
        daily_research_cycle_enabled=True,
        eod_readiness_retry_enabled=True,
    )
    with (
        patch(
            "app.modules.shadow.application.pipeline_status.get_settings",
            return_value=settings,
        ),
        patch(
            "app.modules.shadow.application.pipeline_status.detect_mid_session_activation",
            return_value=(False, "NO_ACTIVITY"),
        ),
    ):
        status = build_pipeline_status(
            session,
            readiness=readiness,
            wm=wm,
            running=False,
            stale=False,
            pending_n=0,
            cycle_covers=True,
            consistency_blocked=False,
            has_portfolios=True,
            now=datetime(2026, 9, 5, 8, 0, tzinfo=UTC),
        )
    assert status.next_session_preparation_status == READY_NO_REBALANCE
    assert status.next_session_summary["code"] == READY_NO_REBALANCE
    assert "message_ru" in status.next_session_summary


def test_missed_cycle_no_retroactive_order_fill() -> None:
    """Catch-up after open must not authorize filling post-open orders at today's OPEN."""
    # Order created mid-session after missed overnight cycle
    created = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    result = can_fill_with_session_open(
        order_created_at=created,
        min_execution_date=date(2026, 9, 8),
        session_date=date(2026, 9, 7),
        open_price=250.0,
        market_status=MarketSessionStatus.OPEN,
        quote_freshness=QuoteFreshness.LIVE,
        observed_at=datetime(2026, 9, 7, 12, 30, tzinfo=UTC),
    )
    assert result.eligible is False


def test_intraday_last_does_not_advance_analytics_watermark() -> None:
    """Intraday LAST quotes live in Redis only — analytics watermark stays candle-based."""
    session = MagicMock()
    eod = date(2026, 9, 3)
    with (
        patch(
            "app.modules.shadow.application.daily_operations.select_latest_complete_as_of"
        ) as sel,
        patch(
            "app.modules.shadow.application.daily_operations._collect_watermarks"
        ) as wm,
    ):
        sel.return_value = SimpleNamespace(
            complete=True,
            as_of=date(2026, 9, 4),
            reason="ok",
            to_dict=lambda: {"complete": True},
        )
        # Market complete EOD is 4th; analytics still 3rd even if intraday LAST exists for 7th
        wm.return_value = {
            "raw_market_latest_date": date(2026, 9, 4),
            "analytics_v2_latest_date": eod,
            "technical_v2_latest_date": eod,
            "intraday_last_trading_date": date(2026, 9, 7),  # must be ignored
        }
        readiness = evaluate_eod_readiness(session)
    assert readiness.ready is False
    assert readiness.blocker_code == WAITING_FOR_ANALYTICS


def test_research_live_mode_enables_three_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings, get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("RESEARCH_LIVE_MODE", "true")
    # Minimal required DB/redis env for Settings
    for key, val in {
        "CORE_DATABASE_HOST": "localhost",
        "CORE_DATABASE_NAME": "core",
        "CORE_DATABASE_USER": "u",
        "CORE_DATABASE_PASSWORD": "p",
        "MEMORY_DATABASE_HOST": "localhost",
        "MEMORY_DATABASE_NAME": "mem",
        "MEMORY_DATABASE_USER": "u",
        "MEMORY_DATABASE_PASSWORD": "p",
        "REDIS_HOST": "localhost",
        "CELERY_BROKER_URL": "redis://localhost:6379/0",
        "CELERY_RESULT_BACKEND": "redis://localhost:6379/1",
    }.items():
        monkeypatch.setenv(key, val)
    monkeypatch.delenv("DAILY_RESEARCH_CYCLE_ENABLED", raising=False)
    monkeypatch.delenv("EOD_READINESS_RETRY_ENABLED", raising=False)
    monkeypatch.delenv("INTRADAY_MARKET_ENABLED", raising=False)

    s = Settings()
    assert s.research_live_mode is True
    assert s.daily_research_cycle_enabled is True
    assert s.eod_readiness_retry_enabled is True
    assert s.intraday_market_enabled is True
    get_settings.cache_clear()


def test_startup_catchup_skips_without_shadow() -> None:
    session = MagicMock()
    settings = SimpleNamespace(research_live_mode=True, eod_readiness_retry_enabled=True)
    with (
        patch(
            "app.modules.shadow.application.daily_operations.get_settings",
            return_value=settings,
        ),
        patch(
            "app.modules.shadow.application.daily_operations._has_active_shadow",
            return_value=False,
        ),
    ):
        out = maybe_startup_catchup(session)
    assert out["stage"] == STAGE_ALREADY_CURRENT
    assert out["reason"] == "no_active_shadow"
