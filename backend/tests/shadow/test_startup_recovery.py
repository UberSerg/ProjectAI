"""SHADOW_STARTUP_RECOVERY_ENABLED — independent of RESEARCH_LIVE_MODE."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.shadow.application.daily_operations import (
    STAGE_DISABLED,
    STAGE_SUCCESS,
    maybe_startup_catchup,
)


def test_startup_recovery_disabled_without_flags() -> None:
    session = MagicMock()
    settings = SimpleNamespace(
        research_live_mode=False,
        eod_readiness_retry_enabled=False,
        shadow_startup_recovery_enabled=False,
    )
    with patch(
        "app.modules.shadow.application.daily_operations.get_settings",
        return_value=settings,
    ):
        out = maybe_startup_catchup(session)
    assert out["status"] == STAGE_DISABLED
    assert out["reason"] == "automation_off"


def test_startup_recovery_enqueues_worker_without_live_mode() -> None:
    session = MagicMock()
    settings = SimpleNamespace(
        research_live_mode=False,
        eod_readiness_retry_enabled=False,
        shadow_startup_recovery_enabled=True,
    )
    fake_task = SimpleNamespace(id="task-abc")
    with (
        patch(
            "app.modules.shadow.application.daily_operations.get_settings",
            return_value=settings,
        ),
        patch(
            "app.modules.shadow.application.daily_operations._has_active_shadow",
            return_value=True,
        ),
        patch("app.worker.tasks.market_shadow_recovery") as recovery_task,
    ):
        recovery_task.delay.return_value = fake_task
        out = maybe_startup_catchup(session)
    assert out["status"] == STAGE_SUCCESS
    assert out["mode"] == "SHADOW_STARTUP_RECOVERY"
    assert out["task_id"] == "task-abc"
    recovery_task.delay.assert_called_once_with()


def test_live_mode_still_uses_cycle_path() -> None:
    session = MagicMock()
    settings = SimpleNamespace(
        research_live_mode=True,
        eod_readiness_retry_enabled=True,
        shadow_startup_recovery_enabled=True,
    )
    with (
        patch(
            "app.modules.shadow.application.daily_operations.get_settings",
            return_value=settings,
        ),
        patch(
            "app.modules.shadow.application.daily_operations._has_active_shadow",
            return_value=True,
        ),
        patch(
            "app.modules.shadow.application.daily_operations.maybe_trigger_cycle_if_ready",
            return_value={"status": STAGE_SUCCESS, "via": "cycle"},
        ) as cycle,
    ):
        out = maybe_startup_catchup(session)
    assert out["via"] == "cycle"
    cycle.assert_called_once()
