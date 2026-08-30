"""Build plaintext diagnostic report for operators / Cursor."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.application.system.event_log import list_events
from app.application.system.health import get_system_health
from app.application.system.info import get_system_info
from app.application.system.sanitize import sanitize_text
from app.infrastructure.market.models import Candle, DataQualityIssue, Instrument, Series, Workflow


def _svc(services: dict[str, str], key: str, label: str) -> str:
    value = services.get(key)
    if value is None:
        return f"{label}: UNKNOWN"
    return f"{label}: {value.upper()}"


def build_diagnostics_text(session: Session) -> str:
    info = get_system_info()
    health = get_system_health()
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    instruments = session.scalar(select(func.count()).select_from(Instrument)) or 0
    candles = session.scalar(select(func.count()).select_from(Candle)) or 0
    series = session.scalar(select(func.count()).select_from(Series)) or 0
    last_ts = session.scalar(select(func.max(Candle.timestamp)))
    dq_errors = (
        session.scalar(
            select(func.count())
            .select_from(DataQualityIssue)
            .where(DataQualityIssue.severity == "error", DataQualityIssue.resolved_at.is_(None))
        )
        or 0
    )
    dq_warnings = (
        session.scalar(
            select(func.count())
            .select_from(DataQualityIssue)
            .where(DataQualityIssue.severity == "warning", DataQualityIssue.resolved_at.is_(None))
        )
        or 0
    )

    workflows = list(
        session.scalars(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .order_by(desc(Workflow.started_at), desc(Workflow.id))
            .limit(10)
        ).all()
    )
    running = list(
        session.scalars(
            select(Workflow)
            .where(Workflow.status.in_(["RUNNING", "PENDING", "running", "pending"]))
            .order_by(desc(Workflow.started_at))
            .limit(20)
        ).all()
    )

    errors = list_events(session, level="ERROR", limit=100)
    warnings = list_events(session, level="WARNING", limit=100)
    infos = list_events(session, level="INFO", limit=200)

    lines: list[str] = [
        "ProjectAI Diagnostic Report",
        f"Generated: {now}",
        "",
        "=== APPLICATION ===",
        "",
        f"Version: {info.version}",
        f"Environment: {info.environment}",
        f"API: {info.api_version}",
        "",
        "=== HEALTH ===",
        "",
        _svc(health.services, "backend", "Backend"),
        _svc(health.services, "core_database", "Core DB"),
        _svc(health.services, "memory_database", "Memory DB"),
        _svc(health.services, "redis", "Redis"),
        _svc(health.services, "worker", "Worker"),
        "Scheduler: NOT MONITORED",
        "",
        "=== MARKET DATA ===",
        "",
        f"Instruments: {instruments}",
        f"Candles: {candles}",
        f"Series: {series}",
        f"Last market data: {last_ts.isoformat() if last_ts else '—'}",
        "",
        "=== WORKFLOWS ===",
        "",
        "Last 10 processes:",
        "",
    ]

    if not workflows:
        lines.append("(none)")
    for wf in workflows:
        lines.append(
            f"- id={wf.id} type={wf.workflow_type or wf.name} status={wf.status} "
            f"started={wf.started_at.isoformat() if wf.started_at else '—'}"
        )
        if wf.error:
            lines.append(f"  error: {sanitize_text(wf.error, max_len=300)}")

    lines.extend(["", "=== RUNNING WORKFLOWS ===", ""])
    if not running:
        lines.append("(none)")
    for wf in running:
        lines.append(f"- id={wf.id} type={wf.workflow_type or wf.name} status={wf.status}")

    lines.extend(
        [
            "",
            "=== DATA QUALITY ===",
            "",
            f"Current errors: {dq_errors}",
            f"Current warnings: {dq_warnings}",
            "",
            "=== ERRORS TODAY ===",
            "",
        ]
    )
    if not errors:
        lines.append("(none)")
    for ev in errors:
        lines.append(
            f"- {ev.timestamp.isoformat() if ev.timestamp else ''} [{ev.component}] "
            f"{ev.event_type}: {ev.message}"
        )
        if ev.workflow_id or ev.trace_id:
            lines.append(f"  workflow_id={ev.workflow_id} trace_id={ev.trace_id}")

    lines.extend(["", "=== RECENT WARNINGS ===", ""])
    if not warnings:
        lines.append("(none)")
    for ev in warnings:
        lines.append(
            f"- {ev.timestamp.isoformat() if ev.timestamp else ''} [{ev.component}] "
            f"{ev.event_type}: {ev.message}"
        )

    lines.extend(["", "=== RECENT EVENTS ===", ""])
    if not infos:
        lines.append("(none)")
    for ev in infos:
        lines.append(
            f"- {ev.timestamp.isoformat() if ev.timestamp else ''} [{ev.component}] "
            f"{ev.event_type}: {ev.message}"
        )

    lines.extend(["", "=== TRACE / IDS ===", ""])
    trace_lines: list[str] = []
    for ev in (*errors[:20], *warnings[:20], *infos[:20]):
        if ev.trace_id or ev.workflow_id:
            trace_lines.append(f"- event={ev.id} workflow_id={ev.workflow_id} trace_id={ev.trace_id}")
    lines.extend(trace_lines or ["(none)"])
    lines.append("")
    return "\n".join(lines)


def build_diagnostics_payload(session: Session) -> dict[str, Any]:
    return {"generated_at": datetime.now(UTC).isoformat(), "text": build_diagnostics_text(session)}
