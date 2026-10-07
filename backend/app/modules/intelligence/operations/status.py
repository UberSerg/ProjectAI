"""Operational status / source-health diagnostics for IntelligenceRefreshV1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.intelligence.operations.config import (
    REFRESH_STAGES,
    REFRESH_WORKFLOW_KEY,
    SOURCE_STALE_HOURS,
)
from app.modules.intelligence.operations.locking import is_refresh_lock_held
from app.modules.intelligence.operations.models import RefreshRun


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return None


def latest_refresh_run(session: Session) -> RefreshRun | None:
    return session.scalar(
        select(RefreshRun)
        .where(RefreshRun.workflow_key == REFRESH_WORKFLOW_KEY)
        .order_by(RefreshRun.id.desc())
        .limit(1)
    )


def last_successful_refresh(session: Session) -> RefreshRun | None:
    return session.scalar(
        select(RefreshRun)
        .where(
            RefreshRun.workflow_key == REFRESH_WORKFLOW_KEY,
            RefreshRun.status.in_(("SUCCESS", "NO_CHANGES", "WARNING")),
        )
        .order_by(RefreshRun.finished_at.desc().nullslast(), RefreshRun.id.desc())
        .limit(1)
    )


def build_source_health(
    session: Session,
    *,
    current_stages: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Per-stage last success + age for OWNER diagnostics."""
    now = now or datetime.now(UTC)
    last = last_successful_refresh(session)
    prior_stages = dict((last.stages if last else None) or {})
    health: dict[str, Any] = {}
    for name in REFRESH_STAGES:
        if name == "FINALIZE":
            continue
        current = (current_stages or {}).get(name) or {}
        prior = prior_stages.get(name) or {}
        finished = _parse_ts(current.get("finished_at")) or _parse_ts(prior.get("finished_at"))
        status = str(current.get("status") or prior.get("status") or "UNKNOWN").upper()
        age_hours: float | None = None
        if finished is not None:
            age_hours = round((now - finished).total_seconds() / 3600.0, 3)
        budget = SOURCE_STALE_HOURS.get(name)
        stale = bool(budget is not None and age_hours is not None and age_hours > budget)
        if status in {"SKIPPED", "PENDING", "UNKNOWN"} and finished is None:
            stale = True
        health[name] = {
            "status": status,
            "last_finished_at": finished.isoformat() if finished else None,
            "age_hours": age_hours,
            "stale_after_hours": budget,
            "stale": stale,
            "reason": current.get("reason") or prior.get("reason"),
        }
    return health


def collect_stale_warnings(source_health: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for name, payload in source_health.items():
        if not payload.get("stale"):
            continue
        warnings.append(
            {
                "source": name,
                "code": "STALE_SOURCE",
                "message": f"{name} is stale or missing successful refresh",
                "age_hours": payload.get("age_hours"),
                "stale_after_hours": payload.get("stale_after_hours"),
                "status": payload.get("status"),
            }
        )
    return warnings


def build_operational_status(session: Session) -> dict[str, Any]:
    """OWNER-facing status snapshot — no aggressive polling side effects."""
    latest = latest_refresh_run(session)
    last_ok = last_successful_refresh(session)
    lock_held = False
    try:
        lock_held = is_refresh_lock_held()
    except Exception:  # noqa: BLE001
        lock_held = False

    stages = dict((latest.stages if latest else None) or {})
    meta = dict((latest.run_metadata if latest else None) or {})
    source_health = build_source_health(session, current_stages=stages)
    stale_warnings = collect_stale_warnings(source_health)

    running = latest is not None and latest.status == "RUNNING"
    # Orphan RUNNING without lock → stale warning only (finalize happens on next run).
    orphan_running = running and not lock_held
    if orphan_running:
        stale_warnings.append(
            {
                "source": "REFRESH_RUN",
                "code": "STALE_RUNNING",
                "message": "RUNNING refresh without lock — will finalize on next OWNER run",
                "refresh_run_id": latest.id if latest else None,
            }
        )

    progress = meta.get("progress") or {
        "completed": sum(
            1
            for s in stages.values()
            if str(s.get("status") or "").upper()
            in {"SUCCESS", "WARNING", "SKIPPED", "FAILED", "ERROR", "NO_CHANGES"}
        ),
        "total": len(REFRESH_STAGES),
    }

    return {
        "workflow_key": REFRESH_WORKFLOW_KEY,
        "lock_held": lock_held,
        "running": running,
        "orphan_running": orphan_running,
        "latest": _row_summary(latest),
        "last_success": _row_summary(last_ok),
        "progress": progress,
        "current_stage": meta.get("current_stage"),
        "stage_status": {name: (stages.get(name) or {}).get("status") for name in REFRESH_STAGES},
        "source_health": source_health,
        "stale_warnings": stale_warnings,
        "polling_policy": {
            "aggressive_polling": False,
            "manual_owner_refresh": True,
            "scheduled_beat": False,
            "note": "Refresh is OWNER/CLI/on-demand only; no Beat schedule for IntelligenceRefreshV1",
        },
    }


def _row_summary(row: RefreshRun | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "refresh_run_id": row.id,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "error_message": row.error_message,
        "changed": bool((row.run_metadata or {}).get("changed")),
        "duration_seconds": (row.run_metadata or {}).get("duration_seconds"),
    }


def hours_since(ts: datetime | None, *, now: datetime | None = None) -> float | None:
    if ts is None:
        return None
    now = now or datetime.now(UTC)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return (now - ts) / timedelta(hours=1)
