"""Same-day technology event journal."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from typing import Any, Literal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.application.system.sanitize import sanitize_text, sanitize_value
from app.core.config import get_settings
from app.infrastructure.market.models import EventLog

Level = Literal["INFO", "WARNING", "ERROR"]

ALLOWED_LEVELS = frozenset({"INFO", "WARNING", "ERROR"})


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def day_start(day: date | None = None) -> datetime:
    d = day or datetime.now(UTC).date()
    return datetime.combine(d, time.min, tzinfo=UTC)


def write_event(
    session: Session,
    *,
    level: Level,
    component: str,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
    workflow_id: int | None = None,
    batch_id: str | None = None,
    instrument_id: int | None = None,
    trace_id: str | None = None,
    enforce_limits: bool = False,
) -> EventLog | None:
    level_u = level.upper()
    if level_u not in ALLOWED_LEVELS:
        return None

    row = EventLog(
        timestamp=datetime.now(UTC),
        level=level_u,
        component=(component or "unknown")[:120],
        event_type=(event_type or "event")[:120],
        message=sanitize_text(message or "", max_len=2000),
        details=sanitize_value(details) if details else None,
        workflow_id=workflow_id,
        batch_id=batch_id,
        instrument_id=instrument_id,
        trace_id=trace_id,
    )
    session.add(row)
    session.flush()

    if enforce_limits:
        cleanup_old_days(session)
        enforce_day_limit(session)
    return row


def cleanup_old_days(session: Session, *, today: date | None = None) -> int:
    """Delete events before the start of the current calendar day (UTC)."""
    cutoff = day_start(today)
    result = session.execute(delete(EventLog).where(EventLog.timestamp < cutoff))
    session.flush()
    return int(result.rowcount or 0)


def enforce_day_limit(session: Session, *, today: date | None = None) -> int:
    settings = get_settings()
    max_events = max(1, int(settings.tech_log_max_events_per_day))
    cutoff = day_start(today)
    count = session.scalar(
        select(func.count()).select_from(EventLog).where(EventLog.timestamp >= cutoff)
    )
    if count is None or count <= max_events:
        return 0
    overflow = int(count) - max_events
    ids = session.scalars(
        select(EventLog.id)
        .where(EventLog.timestamp >= cutoff)
        .order_by(EventLog.timestamp.asc(), EventLog.id.asc())
        .limit(overflow)
    ).all()
    if not ids:
        return 0
    result = session.execute(delete(EventLog).where(EventLog.id.in_(ids)))
    session.flush()
    return int(result.rowcount or 0)


def list_events(
    session: Session,
    *,
    level: str | None = None,
    component: str | None = None,
    workflow_id: int | None = None,
    trace_id: str | None = None,
    limit: int = 200,
) -> list[EventLog]:
    limit = max(1, min(limit, 500))
    stmt = (
        select(EventLog)
        .where(EventLog.timestamp >= day_start())
        .order_by(EventLog.timestamp.desc(), EventLog.id.desc())
    )
    if level:
        stmt = stmt.where(EventLog.level == level.upper())
    if component:
        stmt = stmt.where(EventLog.component == component)
    if workflow_id is not None:
        stmt = stmt.where(EventLog.workflow_id == workflow_id)
    if trace_id:
        stmt = stmt.where(EventLog.trace_id == trace_id)
    stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def get_event(session: Session, event_id: int) -> EventLog | None:
    return session.get(EventLog, event_id)


def event_to_dict(row: EventLog) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "level": row.level,
        "component": row.component,
        "event_type": row.event_type,
        "message": row.message,
        "details": row.details,
        "workflow_id": str(row.workflow_id) if row.workflow_id is not None else None,
        "batch_id": row.batch_id,
        "instrument_id": str(row.instrument_id) if row.instrument_id is not None else None,
        "trace_id": row.trace_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
