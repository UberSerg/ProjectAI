"""IntelligenceRefreshV1 orchestrator.

Reuses research_cycle locking / stage-progress patterns.
Persists runs in intelligence.refresh_runs (not a new workflow framework).
Does not mutate Candidate / Shadow / Daily Decision / broker state.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import get_logger
from app.infrastructure.db.session import core_session
from app.modules.intelligence.isolation import assert_production_isolation
from app.modules.intelligence.operations.config import (
    MAX_STAGE_RETRIES,
    REFRESH_NAME,
    REFRESH_STAGES,
    REFRESH_WORKFLOW_KEY,
    RETRY_BACKOFF_SECONDS,
)
from app.modules.intelligence.operations.locking import try_acquire_refresh_lock
from app.modules.intelligence.operations.models import RefreshRun
from app.modules.intelligence.operations.stages import (
    DEFAULT_STAGE_RUNNERS,
    StageFn,
    run_stage_with_retries,
)

logger = get_logger(__name__, component="intelligence-refresh")


def _now() -> datetime:
    return datetime.now(UTC)


def _empty_stages() -> dict[str, Any]:
    return {
        name: {
            "status": "PENDING",
            "started_at": None,
            "finished_at": None,
            "attempts": 0,
            "changed": False,
            "reason": None,
            "error": None,
            "details": {},
        }
        for name in REFRESH_STAGES
    }


def _progress(stages: dict[str, Any]) -> dict[str, int]:
    terminal = {"SUCCESS", "WARNING", "SKIPPED", "FAILED", "ERROR", "NO_CHANGES"}
    completed = sum(1 for s in stages.values() if str(s.get("status") or "").upper() in terminal)
    return {"completed": completed, "total": len(REFRESH_STAGES)}


def _fingerprint(ctx: dict[str, Any]) -> str:
    instruments = ctx.get("instrument_ids") or []
    as_of = ctx.get("as_of")
    parts = [
        REFRESH_WORKFLOW_KEY,
        str(as_of or ""),
        ",".join(str(i) for i in instruments),
    ]
    return "|".join(parts)


def _find_idempotent_hit(session: Session, fingerprint: str) -> RefreshRun | None:
    """Return latest SUCCESS/NO_CHANGES run with same fingerprint (idempotent short-circuit)."""
    rows = session.scalars(
        select(RefreshRun)
        .where(
            RefreshRun.workflow_key == REFRESH_WORKFLOW_KEY,
            RefreshRun.status.in_(("SUCCESS", "NO_CHANGES", "WARNING")),
        )
        .order_by(RefreshRun.id.desc())
        .limit(20)
    ).all()
    for row in rows:
        meta = dict(row.run_metadata or {})
        if meta.get("fingerprint") == fingerprint:
            return row
    return None


def _finalize_stale_running(session: Session) -> list[int]:
    """If Redis lock is free but DB rows are RUNNING, they are orphaned — finalize FAILED."""
    running = session.scalars(
        select(RefreshRun).where(
            RefreshRun.workflow_key == REFRESH_WORKFLOW_KEY,
            RefreshRun.status == "RUNNING",
        )
    ).all()
    touched: list[int] = []
    for row in running:
        row.status = "FAILED"
        row.error_message = "STALE_RUNNING: lock acquired but prior refresh left RUNNING"
        row.finished_at = _now()
        meta = dict(row.run_metadata or {})
        meta["stale_finalized"] = True
        row.run_metadata = meta
        flag_modified(row, "run_metadata")
        touched.append(row.id)
    if touched:
        session.flush()
    return touched


def run_intelligence_refresh(
    session: Session | None = None,
    *,
    instrument_ids: list[int] | None = None,
    as_of: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    stage_runners: dict[str, StageFn] | None = None,
    max_retries: int = MAX_STAGE_RETRIES,
    backoff_seconds: float = RETRY_BACKOFF_SECONDS,
    skip_lock: bool = False,
) -> dict[str, Any]:
    """Run one IntelligenceRefreshV1. OWNER / CLI / on-demand Celery entrypoint."""
    owns_session = session is None
    if owns_session:
        with core_session() as owned:
            return _run(
                owned,
                instrument_ids=instrument_ids,
                as_of=as_of,
                force=force,
                dry_run=dry_run,
                stage_runners=stage_runners,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
                skip_lock=skip_lock,
            )
    assert session is not None
    return _run(
        session,
        instrument_ids=instrument_ids,
        as_of=as_of,
        force=force,
        dry_run=dry_run,
        stage_runners=stage_runners,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        skip_lock=skip_lock,
    )


def _run(
    session: Session,
    *,
    instrument_ids: list[int] | None,
    as_of: str | None,
    force: bool,
    dry_run: bool,
    stage_runners: dict[str, StageFn] | None,
    max_retries: int,
    backoff_seconds: float,
    skip_lock: bool,
) -> dict[str, Any]:
    assert_production_isolation()

    ctx: dict[str, Any] = {
        "instrument_ids": list(instrument_ids or []),
        "as_of": as_of,
        "dry_run": dry_run,
        "force": force,
        "live_fetch": bool(force) and not dry_run,
        "stage_results": {},
    }
    fingerprint = _fingerprint(ctx)

    if not force and not dry_run:
        hit = _find_idempotent_hit(session, fingerprint)
        if hit is not None:
            return {
                "status": "NO_CHANGES",
                "reason": "IDEMPOTENT_HIT",
                "refresh_run_id": hit.id,
                "fingerprint": fingerprint,
                "message": "Identical refresh fingerprint already completed; use --force to re-run",
                "stages": hit.stages,
                "progress": _progress(dict(hit.stages or {})),
                "prior_status": hit.status,
            }

    token = str(uuid.uuid4())
    lock = None
    if not skip_lock:
        lock = try_acquire_refresh_lock(token)
        if not lock.acquired:
            return {
                "status": "BLOCKED",
                "reason": "ALREADY_RUNNING",
                "message": "IntelligenceRefreshV1 already running",
                "fingerprint": fingerprint,
            }

    started = time.perf_counter()
    run: RefreshRun | None = None
    runners = {**DEFAULT_STAGE_RUNNERS, **(stage_runners or {})}

    try:
        stale_ids = _finalize_stale_running(session)
        stages = _empty_stages()
        run = RefreshRun(
            workflow_key=REFRESH_WORKFLOW_KEY,
            status="RUNNING",
            stages=stages,
            started_at=_now(),
            run_metadata={
                "name": REFRESH_NAME,
                "fingerprint": fingerprint,
                "instrument_ids": ctx["instrument_ids"],
                "as_of": as_of,
                "dry_run": dry_run,
                "force": force,
                "progress": _progress(stages),
                "stale_running_finalized": stale_ids,
                "source_health": {},
                "stale_warnings": [],
            },
        )
        session.add(run)
        session.flush()

        if dry_run:
            for name in REFRESH_STAGES:
                stages[name] = {
                    "status": "SKIPPED",
                    "reason": "DRY_RUN",
                    "started_at": _now().isoformat(),
                    "finished_at": _now().isoformat(),
                    "attempts": 0,
                    "changed": False,
                    "error": None,
                    "details": {},
                }
            run.stages = stages
            flag_modified(run, "stages")
            run.status = "NO_CHANGES"
            run.finished_at = _now()
            meta = dict(run.run_metadata or {})
            meta["progress"] = _progress(stages)
            meta["changed"] = False
            meta["duration_seconds"] = round(time.perf_counter() - started, 3)
            run.run_metadata = meta
            flag_modified(run, "run_metadata")
            session.flush()
            return {
                "status": "NO_CHANGES",
                "reason": "DRY_RUN",
                "refresh_run_id": run.id,
                "fingerprint": fingerprint,
                "stages": stages,
                "progress": meta["progress"],
                "duration_seconds": meta["duration_seconds"],
            }

        any_changed = False
        any_failed = False
        stage_results: dict[str, Any] = {}

        for name in REFRESH_STAGES:
            stages[name]["status"] = "RUNNING"
            stages[name]["started_at"] = _now().isoformat()
            run.stages = stages
            flag_modified(run, "stages")
            meta = dict(run.run_metadata or {})
            meta["progress"] = _progress(stages)
            meta["current_stage"] = name
            run.run_metadata = meta
            flag_modified(run, "run_metadata")
            session.flush()

            ctx["stage_results"] = stage_results
            runner = runners[name]
            result = run_stage_with_retries(
                session,
                name,
                runner,
                ctx,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
            )
            payload = result.to_dict()
            stages[name] = {
                "status": result.status,
                "reason": result.reason,
                "started_at": stages[name]["started_at"],
                "finished_at": _now().isoformat(),
                "attempts": result.attempts,
                "changed": result.changed,
                "error": result.error,
                "details": result.details,
            }
            stage_results[name] = payload
            if result.changed:
                any_changed = True
            if result.status.upper() in {"FAILED", "ERROR"}:
                any_failed = True

            run.stages = stages
            flag_modified(run, "stages")
            meta = dict(run.run_metadata or {})
            meta["progress"] = _progress(stages)
            meta["changed"] = any_changed
            run.run_metadata = meta
            flag_modified(run, "run_metadata")
            session.flush()

        from app.modules.intelligence.operations.status import (
            build_source_health,
            collect_stale_warnings,
        )

        source_health = build_source_health(session, current_stages=stages)
        stale_warnings = collect_stale_warnings(source_health)

        if any_failed:
            final_status = "WARNING"
        elif any_changed:
            final_status = "SUCCESS"
        else:
            final_status = "NO_CHANGES"

        duration = round(time.perf_counter() - started, 3)
        run.status = final_status
        run.finished_at = _now()
        meta = dict(run.run_metadata or {})
        meta.update(
            {
                "progress": _progress(stages),
                "changed": any_changed,
                "duration_seconds": duration,
                "source_health": source_health,
                "stale_warnings": stale_warnings,
                "current_stage": None,
            }
        )
        run.run_metadata = meta
        flag_modified(run, "run_metadata")
        session.flush()

        return {
            "status": final_status,
            "refresh_run_id": run.id,
            "fingerprint": fingerprint,
            "stages": stages,
            "progress": meta["progress"],
            "changed": any_changed,
            "duration_seconds": duration,
            "source_health": source_health,
            "stale_warnings": stale_warnings,
            "last_success": _serialize_last_success(session),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("intelligence_refresh_failed", extra={"error": str(exc)})
        session.rollback()
        if run is not None and run.id is not None:
            try:
                row = session.get(RefreshRun, run.id)
                if row is not None:
                    row.status = "FAILED"
                    row.error_message = str(exc)[:2000]
                    row.finished_at = _now()
                    session.flush()
            except Exception:
                session.rollback()
        return {
            "status": "FAILED",
            "error": str(exc),
            "refresh_run_id": run.id if run is not None else None,
            "fingerprint": fingerprint,
        }
    finally:
        if lock is not None:
            lock.release()


def _serialize_last_success(session: Session) -> dict[str, Any] | None:
    row = session.scalar(
        select(RefreshRun)
        .where(
            RefreshRun.workflow_key == REFRESH_WORKFLOW_KEY,
            RefreshRun.status.in_(("SUCCESS", "NO_CHANGES", "WARNING")),
        )
        .order_by(RefreshRun.finished_at.desc().nullslast(), RefreshRun.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    return {
        "refresh_run_id": row.id,
        "status": row.status,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
    }


__all__ = [
    "run_intelligence_refresh",
]
