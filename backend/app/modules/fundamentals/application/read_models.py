"""Read models for the fundamentals API. Payloads are honest: empty stays empty."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.modules.fundamentals.application import pit
from app.modules.fundamentals.application.audit import build_source_audit_report
from app.modules.fundamentals.application.readiness import build_readiness_report, coverage
from app.modules.fundamentals.config import fundamentals_update_enabled
from app.modules.fundamentals.domain.types import (
    FUNDAMENTALS_VERSION,
    ReadinessStatus,
)
from app.modules.fundamentals.infrastructure.models import (
    CorporateEvent,
    DividendEvent,
    FinancialReport,
    IngestionRun,
    Issuer,
    MetricRegistryEntry,
    SecurityIssuerMapping,
    fundamentals_schema_ready,
)

NOT_READY_REASON = "fundamentals schema missing; apply alembic 20260905_0018"


def _not_ready(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": ReadinessStatus.NOT_READY.value,
        "reason": NOT_READY_REASON,
        "version": FUNDAMENTALS_VERSION,
    }
    payload.update(extra or {})
    return payload


def status_payload(session: Session) -> dict[str, Any]:
    if not fundamentals_schema_ready(session):
        return _not_ready({"coverage": {}, "last_runs": []})
    runs = session.scalars(
        select(IngestionRun).order_by(desc(IngestionRun.started_at)).limit(10)
    ).all()
    readiness = build_readiness_report(session)
    return {
        "status": readiness["status"],
        "version": FUNDAMENTALS_VERSION,
        "update_enabled": fundamentals_update_enabled(),
        "coverage": readiness["coverage"],
        "blockers": readiness["blockers"],
        "last_runs": [
            {
                "id": run.id,
                "provider": run.provider,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "requested_range": run.requested_range,
            }
            for run in runs
        ],
    }


def source_audit_payload(session: Session) -> dict[str, Any]:
    """Audit verdicts are static data; the last persisted run id is attached when present."""
    report = build_source_audit_report()
    if fundamentals_schema_ready(session):
        last = session.scalar(
            select(IngestionRun)
            .where(IngestionRun.provider == "SOURCE_AUDIT")
            .order_by(desc(IngestionRun.started_at))
            .limit(1)
        )
        report["last_run_id"] = last.id if last else None
    return report


def coverage_payload(session: Session) -> dict[str, Any]:
    if not fundamentals_schema_ready(session):
        return _not_ready({"coverage": {}})
    return {"status": "OK", "version": FUNDAMENTALS_VERSION, "coverage": coverage(session)}


def readiness_payload(session: Session) -> dict[str, Any]:
    return build_readiness_report(session)


def metrics_payload(session: Session) -> dict[str, Any]:
    if not fundamentals_schema_ready(session):
        return _not_ready({"metrics": []})
    rows = session.scalars(select(MetricRegistryEntry).order_by(MetricRegistryEntry.code)).all()
    return {
        "status": "OK",
        "metrics": [
            {
                "code": row.code,
                "title_ru": row.title_ru,
                "title_en": row.title_en,
                "description": row.description,
                "applies_to_banks": row.applies_to_banks,
                "status": row.status,
            }
            for row in rows
        ],
    }


def issuers_payload(session: Session, *, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    if not fundamentals_schema_ready(session):
        return _not_ready({"issuers": [], "total": 0})
    total = int(session.execute(select(func.count()).select_from(Issuer)).scalar_one())
    rows = session.scalars(
        select(Issuer).order_by(Issuer.title).limit(limit).offset(offset)
    ).all()
    mapping_counts = dict(
        session.execute(
            select(SecurityIssuerMapping.issuer_id, func.count())
            .where(SecurityIssuerMapping.issuer_id.is_not(None))
            .group_by(SecurityIssuerMapping.issuer_id)
        ).all()
    )
    return {
        "status": "OK",
        "total": total,
        "issuers": [
            {
                "id": row.id,
                "moex_emitent_id": row.moex_emitent_id,
                "title": row.title,
                "title_en": row.title_en,
                "inn": row.inn,
                "okpo": row.okpo,
                "instrument_count": int(mapping_counts.get(row.id, 0)),
            }
            for row in rows
        ],
    }


def mappings_payload(
    session: Session, *, mapping_status: str | None = None, limit: int = 200
) -> dict[str, Any]:
    if not fundamentals_schema_ready(session):
        return _not_ready({"mappings": []})
    stmt = select(SecurityIssuerMapping).order_by(SecurityIssuerMapping.instrument_id)
    if mapping_status:
        stmt = stmt.where(SecurityIssuerMapping.mapping_status == mapping_status.upper())
    rows = session.scalars(stmt.limit(limit)).all()
    return {
        "status": "OK",
        "mappings": [
            {
                "id": row.id,
                "instrument_id": row.instrument_id,
                "issuer_id": row.issuer_id,
                "external_secid": row.external_secid,
                "isin": row.isin,
                "mapping_status": row.mapping_status,
                "valid_from": row.valid_from.isoformat() if row.valid_from else None,
                "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                "source": row.source,
            }
            for row in rows
        ],
    }


def reports_payload(
    session: Session, *, issuer_id: int, as_of: date | None = None
) -> dict[str, Any]:
    """Point-in-time view: with as_of set, only reports disclosed by then are returned."""
    if not fundamentals_schema_ready(session):
        return _not_ready({"reports": [], "latest_report": None})
    effective_as_of = as_of or date.today()
    state = pit.get_fundamentals_as_of(session, issuer_id, effective_as_of)
    latest = state.latest_report
    total = int(
        session.execute(
            select(func.count())
            .select_from(FinancialReport)
            .where(FinancialReport.issuer_id == issuer_id)
        ).scalar_one()
    )
    return {
        "status": "OK" if latest is not None else ReadinessStatus.NOT_READY.value,
        "issuer_id": issuer_id,
        "as_of": effective_as_of.isoformat(),
        "reports_stored": total,
        "reports_visible": state.visible_reports,
        "latest_report": (
            {
                "report_id": latest.report_id,
                "reporting_standard": str(latest.reporting_standard),
                "period_type": str(latest.period_type),
                "period_start": latest.period_start.isoformat() if latest.period_start else None,
                "period_end": latest.period_end.isoformat(),
                "known_at": latest.known_at.isoformat(),
                "report_version": latest.report_version,
                "is_restatement": latest.is_restatement,
                "source": latest.source,
            }
            if latest is not None
            else None
        ),
        "facts": [
            {
                "metric_code": fact.metric_code,
                "value": fact.value,
                "currency": fact.currency,
                "unit_scale": fact.unit_scale,
                "normalization_status": str(fact.normalization_status),
                "quality_status": str(fact.quality_status),
            }
            for fact in state.facts
        ],
    }


def dividends_payload(
    session: Session,
    *,
    as_of: date | None = None,
    instrument_id: int | None = None,
    issuer_id: int | None = None,
) -> dict[str, Any]:
    if not fundamentals_schema_ready(session):
        return _not_ready({"state": None, "events": []})
    effective_as_of = as_of or date.today()
    events = pit.load_visible_dividend_events(
        session, effective_as_of, instrument_id=instrument_id, issuer_id=issuer_id
    )
    state = pit.get_dividend_state_as_of(
        session, effective_as_of, instrument_id=instrument_id, issuer_id=issuer_id
    )
    upcoming = pit.get_upcoming_dividend_as_of(
        session, effective_as_of, instrument_id=instrument_id, issuer_id=issuer_id
    )
    stored = int(session.execute(select(func.count()).select_from(DividendEvent)).scalar_one())
    return {
        "status": "OK" if state.is_known else ReadinessStatus.NOT_READY.value,
        "as_of": effective_as_of.isoformat(),
        "instrument_id": instrument_id,
        "issuer_id": issuer_id,
        "events_stored_total": stored,
        "events_visible": len(events),
        "state": _dividend_state_dict(state),
        "upcoming": _dividend_state_dict(upcoming) if upcoming is not None else None,
        "note": (
            "Empty because both MOEX ISS dividend endpoints were rejected by the source "
            "audit. Dividends are not credited to any portfolio."
        )
        if stored == 0
        else None,
    }


def _dividend_state_dict(state: Any) -> dict[str, Any]:
    payload = asdict(state)
    for key, value in list(payload.items()):
        if isinstance(value, date):
            payload[key] = value.isoformat()
    payload["status"] = str(state.status)
    return payload


def events_payload(
    session: Session,
    *,
    as_of: date | None = None,
    instrument_id: int | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    if not fundamentals_schema_ready(session):
        return _not_ready({"events": []})
    effective_as_of = as_of or date.today()
    stmt = select(CorporateEvent).where(CorporateEvent.known_at <= effective_as_of)
    if instrument_id is not None:
        stmt = stmt.where(CorporateEvent.instrument_id == instrument_id)
    rows = session.scalars(
        stmt.order_by(desc(CorporateEvent.event_date)).limit(limit)
    ).all()
    return {
        "status": "OK" if rows else ReadinessStatus.NOT_READY.value,
        "as_of": effective_as_of.isoformat(),
        "instrument_id": instrument_id,
        "events": [
            {
                "id": row.id,
                "event_type": row.event_type,
                "event_date": row.event_date.isoformat(),
                "known_at": row.known_at.isoformat(),
                "known_at_basis": (row.payload or {}).get("known_at_basis"),
                "effective_date": row.effective_date.isoformat() if row.effective_date else None,
                "instrument_id": row.instrument_id,
                "issuer_id": row.issuer_id,
                "source": row.source,
            }
            for row in rows
        ],
    }
