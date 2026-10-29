"""RECOVERING only when recovery is actually running — not merely backlog."""

from __future__ import annotations

from unittest.mock import patch

from app.modules.shadow.application.daily_operations import _map_operational_state
from app.modules.shadow.application.pipeline_status import (
    READY_FOR_NEXT_SESSION,
    WAITING_FOR_FORWARD,
)


def test_backlog_without_lock_is_stale_not_recovering() -> None:
    with patch(
        "app.modules.shadow.application.daily_operations._recovery_runtime",
        return_value={
            "running": False,
            "lock_held": False,
            "task_id": None,
            "started_at": None,
            "updated_at": None,
            "phase": None,
            "last_completed_session": None,
            "remaining_sessions": 20,
            "blocking_session": None,
            "blocker": None,
            "status_state": None,
        },
    ):
        out = _map_operational_state(
            prep=WAITING_FOR_FORWARD,
            current="NO_ACTIVITY",
            catch_up={"catch_up_status": "CATCH_UP_PARTIAL", "backlog_session_count": 20},
            automation_warning=None,
            order_plan_status="NONE",
        )
    assert out["state"] == "STALE_DATA"
    assert out["backlog_without_recovery"] is True


def test_lock_held_is_recovering() -> None:
    with patch(
        "app.modules.shadow.application.daily_operations._recovery_runtime",
        return_value={
            "running": True,
            "lock_held": True,
            "task_id": "abc",
            "started_at": "2026-10-28T10:00:00+00:00",
            "updated_at": "2026-10-28T10:05:00+00:00",
            "phase": "shadow",
            "last_completed_session": "2026-10-01",
            "remaining_sessions": 12,
            "blocking_session": None,
            "blocker": None,
            "status_state": "RUNNING",
        },
    ):
        out = _map_operational_state(
            prep=WAITING_FOR_FORWARD,
            current="NO_ACTIVITY",
            catch_up={"catch_up_status": "CATCH_UP_PARTIAL", "backlog_session_count": 12},
            automation_warning=None,
            order_plan_status="NONE",
        )
    assert out["state"] == "RECOVERING"
    assert out["recovery"]["task_id"] == "abc"
    assert out["backlog_without_recovery"] is False


def test_ready_when_no_backlog() -> None:
    with patch(
        "app.modules.shadow.application.daily_operations._recovery_runtime",
        return_value={
            "running": False,
            "lock_held": False,
            "task_id": None,
            "started_at": None,
            "updated_at": None,
            "phase": None,
            "last_completed_session": None,
            "remaining_sessions": None,
            "blocking_session": None,
            "blocker": None,
            "status_state": None,
        },
    ):
        out = _map_operational_state(
            prep=READY_FOR_NEXT_SESSION,
            current="NO_ACTIVITY",
            catch_up={"catch_up_status": "CATCH_UP_NO_OP", "backlog_session_count": 0},
            automation_warning=None,
            order_plan_status="PRESENT",
        )
    assert out["state"] == "READY"
