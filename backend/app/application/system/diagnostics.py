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
from app.infrastructure.analytics.models import FeatureRun, FeatureSet, InstrumentFeatureDaily
from app.infrastructure.analytics.relation_models import RelationInput, RelationRun, RelationSet, RelationSnapshot
from app.infrastructure.market.models import Candle, DataQualityIssue, Instrument, Series, Workflow
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.relations.application.seed import seed_relation_sets


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
    ]

    seed_feature_sets(session)
    active_fs = session.scalar(select(FeatureSet).where(FeatureSet.is_active.is_(True)))
    last_success_run = session.scalar(
        select(FeatureRun)
        .where(FeatureRun.status.in_(["SUCCESS", "WARNING"]))
        .order_by(desc(FeatureRun.finished_at))
        .limit(1)
    )
    analytics_latest = None
    instrument_feat_rows = 0
    series_feat_rows = 0
    invalid_rows = 0
    warning_rows = 0
    last_analytics_error = session.scalar(
        select(FeatureRun).where(FeatureRun.status == "ERROR").order_by(desc(FeatureRun.created_at)).limit(1)
    )
    if active_fs:
        analytics_latest = session.scalar(
            select(func.max(InstrumentFeatureDaily.date)).where(
                InstrumentFeatureDaily.feature_set_id == active_fs.id
            )
        )
        instrument_feat_rows = (
            session.scalar(
                select(func.count())
                .select_from(InstrumentFeatureDaily)
                .where(InstrumentFeatureDaily.feature_set_id == active_fs.id)
            )
            or 0
        )
        from app.infrastructure.analytics.models import SeriesFeatureDaily

        series_feat_rows = (
            session.scalar(
                select(func.count())
                .select_from(SeriesFeatureDaily)
                .where(SeriesFeatureDaily.feature_set_id == active_fs.id)
            )
            or 0
        )
        invalid_rows = (
            session.scalar(
                select(func.count())
                .select_from(InstrumentFeatureDaily)
                .where(
                    InstrumentFeatureDaily.feature_set_id == active_fs.id,
                    InstrumentFeatureDaily.is_valid.is_(False),
                )
            )
            or 0
        )
        warning_rows = (
            session.scalar(
                select(func.count())
                .select_from(InstrumentFeatureDaily)
                .where(
                    InstrumentFeatureDaily.feature_set_id == active_fs.id,
                    InstrumentFeatureDaily.quality_flags.contains({"price_discontinuity": True}),
                )
            )
            or 0
        )

    last_run_ts = (
        last_success_run.finished_at.isoformat()
        if last_success_run and last_success_run.finished_at
        else "—"
    )
    lines.extend(
        [
            "=== ANALYTICS ===",
            "",
            f"Active feature set: {active_fs.code} v{active_fs.version}" if active_fs else "Active feature set: —",
            f"Last successful feature run: {last_run_ts}",
            f"Latest calculated market date: {analytics_latest.isoformat() if analytics_latest else '—'}",
            f"Instrument feature rows: {instrument_feat_rows}",
            f"Series feature rows: {series_feat_rows}",
            f"Invalid rows: {invalid_rows}",
            f"Rows with quality warnings: {warning_rows}",
            f"Last analytics error: {last_analytics_error.error_message if last_analytics_error else '—'}",
            "",
        ]
    )

    seed_relation_sets(session)
    active_rs = session.scalar(select(RelationSet).where(RelationSet.is_active.is_(True)))
    last_rel_run = session.scalar(
        select(RelationRun)
        .where(RelationRun.status.in_(["SUCCESS", "WARNING", "NO_CHANGES"]))
        .order_by(desc(RelationRun.finished_at))
        .limit(1)
    )
    latest_as_of = session.scalar(select(func.max(RelationSnapshot.as_of_date)))
    inputs_active = (
        session.scalar(select(func.count()).select_from(RelationInput).where(RelationInput.is_active.is_(True)))
        or 0
    )
    snap_total = session.scalar(select(func.count()).select_from(RelationSnapshot)) or 0
    snap_valid = (
        session.scalar(
            select(func.count()).select_from(RelationSnapshot).where(RelationSnapshot.is_valid.is_(True))
        )
        or 0
    )
    snap_invalid = (
        session.scalar(
            select(func.count()).select_from(RelationSnapshot).where(RelationSnapshot.is_valid.is_(False))
        )
        or 0
    )
    last_rel_error = session.scalar(
        select(RelationRun).where(RelationRun.status == "ERROR").order_by(desc(RelationRun.created_at)).limit(1)
    )
    last_rel_ts = (
        last_rel_run.finished_at.isoformat() if last_rel_run and last_rel_run.finished_at else "—"
    )

    lines.extend(
        [
            "=== RELATIONS ===",
            "",
            (
                f"Active relation set: {active_rs.code} v{active_rs.version}"
                if active_rs
                else "Active relation set: —"
            ),
            f"Active relation inputs: {inputs_active}",
            f"Last successful relation run: {last_rel_ts}",
            f"Latest as_of_date: {latest_as_of.isoformat() if latest_as_of else '—'}",
            f"Snapshots total: {snap_total}",
            f"Snapshots valid: {snap_valid}",
            f"Snapshots invalid: {snap_invalid}",
            f"Last relations error: {last_rel_error.error_message if last_rel_error else '—'}",
            "",
            "=== WORKFLOWS ===",
            "",
            "Last 10 processes:",
            "",
        ]
    )

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
    now_utc = datetime.now(UTC)
    for wf in running:
        age_min = "—"
        stale_hint = ""
        if wf.started_at is not None:
            started = wf.started_at if wf.started_at.tzinfo else wf.started_at.replace(tzinfo=UTC)
            age = (now_utc - started).total_seconds() / 60.0
            age_min = f"{age:.0f}m"
            # Light signal only — no auto-recovery. Worker death can leave RUNNING forever.
            if age >= 15:
                stale_hint = " [POSSIBLY STALE — check meta heartbeat / abort manually if worker restarted]"
        meta = wf.meta or {}
        progress = meta.get("as_of_progress") or meta.get("persist_progress") or ""
        progress_bit = f" progress={progress}" if progress else ""
        lines.append(
            f"- id={wf.id} type={wf.workflow_type or wf.name} status={wf.status} "
            f"age={age_min}{progress_bit}{stale_hint}"
        )

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
