"""Analytics API — feature sets, runs, instrument/series features."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from app.infrastructure.analytics.models import FeatureRun, FeatureSet, InstrumentFeatureDaily, SeriesFeatureDaily
from app.infrastructure.db.session import core_session
from app.infrastructure.market.models import Instrument
from app.modules.analytics.application.resolve import FeatureSetResolveError, resolve_feature_set
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.analytics.feature_config import FEATURE_BACKFILL_STEPS
from app.modules.market.application.workflows import create_workflow
from app.worker import tasks as worker_tasks

router = APIRouter()


class FeatureSetResponse(BaseModel):
    id: str
    code: str
    version: int
    description: str | None
    parameters: dict[str, Any]
    is_active: bool


class FeatureRunResponse(BaseModel):
    id: str
    feature_set_id: str
    feature_set_code: str | None = None
    feature_set_version: int | None = None
    run_type: str
    date_from: date | None
    date_to: date | None
    started_at: str | None
    finished_at: str | None
    status: str
    instruments_total: int
    instrument_rows_calculated: int
    series_rows_calculated: int
    rows_valid: int
    rows_invalid: int
    rows_skipped: int
    source_watermark: str | None
    error_message: str | None
    workflow_id: str | None


class InstrumentFeatureResponse(BaseModel):
    id: str
    instrument_id: str
    date: date
    timeframe: str
    feature_set_id: str
    feature_version: int
    close: float | None
    volume: float | None
    return_1d: float | None
    return_2d: float | None
    return_3d: float | None
    return_5d: float | None
    return_10d: float | None
    return_20d: float | None
    log_return_1d: float | None
    volatility_5d: float | None
    volatility_20d: float | None
    drawdown_20d: float | None
    volume_change_1d: float | None
    volume_zscore_20d: float | None
    has_sufficient_history: bool
    is_valid: bool
    quality_flags: dict[str, Any]
    calculated_at: str | None


class BackfillRequest(BaseModel):
    date_from: date
    date_to: date | None = None
    feature_set_code: str = "basic_daily"
    feature_set_version: int = 1


class WorkflowCreated(BaseModel):
    workflow_id: int
    status: str


def _dec(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _feature_set_dict(row: FeatureSet) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "version": row.version,
        "description": row.description,
        "parameters": row.parameters,
        "is_active": row.is_active,
    }


def _feature_run_dict(row: FeatureRun, feature_set: FeatureSet | None = None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "feature_set_id": str(row.feature_set_id),
        "feature_set_code": feature_set.code if feature_set else None,
        "feature_set_version": feature_set.version if feature_set else None,
        "run_type": row.run_type,
        "date_from": row.date_from,
        "date_to": row.date_to,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "status": row.status,
        "instruments_total": row.instruments_total,
        "instrument_rows_calculated": row.instrument_rows_calculated,
        "series_rows_calculated": row.series_rows_calculated,
        "rows_valid": row.rows_valid,
        "rows_invalid": row.rows_invalid,
        "rows_skipped": row.rows_skipped,
        "source_watermark": row.source_watermark.isoformat() if row.source_watermark else None,
        "error_message": row.error_message,
        "workflow_id": str(row.workflow_id) if row.workflow_id else None,
    }


def _instrument_feature_dict(row: InstrumentFeatureDaily) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "instrument_id": str(row.instrument_id),
        "date": row.date,
        "timeframe": row.timeframe,
        "feature_set_id": str(row.feature_set_id),
        "feature_version": row.feature_version,
        "close": _dec(row.close),
        "volume": _dec(row.volume),
        "return_1d": _dec(row.return_1d),
        "return_2d": _dec(row.return_2d),
        "return_3d": _dec(row.return_3d),
        "return_5d": _dec(row.return_5d),
        "return_10d": _dec(row.return_10d),
        "return_20d": _dec(row.return_20d),
        "log_return_1d": _dec(row.log_return_1d),
        "volatility_5d": _dec(row.volatility_5d),
        "volatility_20d": _dec(row.volatility_20d),
        "drawdown_20d": _dec(row.drawdown_20d),
        "volume_change_1d": _dec(row.volume_change_1d),
        "volume_zscore_20d": _dec(row.volume_zscore_20d),
        "has_sufficient_history": row.has_sufficient_history,
        "is_valid": row.is_valid,
        "quality_flags": row.quality_flags or {},
        "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
    }


def _resolve_or_http(session, code: str, version: int | None) -> FeatureSet:
    try:
        return resolve_feature_set(session, code, version)
    except FeatureSetResolveError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("/features/sets")
def list_feature_sets() -> dict[str, Any]:
    with core_session() as session:
        seed_feature_sets(session)
        rows = list(session.scalars(select(FeatureSet).order_by(FeatureSet.code, FeatureSet.version)))
        return {"items": [_feature_set_dict(row) for row in rows], "total": len(rows)}


@router.get("/features/runs")
def list_feature_runs(
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    with core_session() as session:
        rows = list(
            session.scalars(select(FeatureRun).order_by(desc(FeatureRun.created_at)).limit(limit))
        )
        fs_ids = {row.feature_set_id for row in rows}
        sets = {
            fs.id: fs
            for fs in session.scalars(select(FeatureSet).where(FeatureSet.id.in_(fs_ids))).all()
        } if fs_ids else {}
        return {
            "items": [_feature_run_dict(row, sets.get(row.feature_set_id)) for row in rows],
            "total": len(rows),
        }


@router.get("/features/runs/{run_id}")
def get_feature_run(run_id: int) -> dict[str, Any]:
    with core_session() as session:
        row = session.get(FeatureRun, run_id)
        if row is None:
            raise HTTPException(404, "Feature run not found")
        fs = session.get(FeatureSet, row.feature_set_id)
        return _feature_run_dict(row, fs)


@router.get("/instruments/{instrument_id}/features")
def list_instrument_features(
    instrument_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    feature_set_code: str | None = None,
    feature_set_version: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    with core_session() as session:
        if session.get(Instrument, instrument_id) is None:
            raise HTTPException(404, "Instrument not found")
        filters = [InstrumentFeatureDaily.instrument_id == instrument_id]
        if date_from:
            filters.append(InstrumentFeatureDaily.date >= date_from)
        if date_to:
            filters.append(InstrumentFeatureDaily.date <= date_to)
        if feature_set_code:
            fs = _resolve_or_http(session, feature_set_code, feature_set_version)
            filters.append(InstrumentFeatureDaily.feature_set_id == fs.id)
        elif feature_set_version is not None:
            raise HTTPException(400, "feature_set_version requires feature_set_code")
        base = select(InstrumentFeatureDaily).where(*filters)
        total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = session.scalars(
            base.order_by(desc(InstrumentFeatureDaily.date))
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "items": [_instrument_feature_dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/instruments/{instrument_id}/features/latest")
def latest_instrument_features(
    instrument_id: int,
    feature_set_code: str = "basic_daily",
    feature_set_version: int | None = Query(None, ge=1),
) -> dict[str, Any]:
    with core_session() as session:
        if session.get(Instrument, instrument_id) is None:
            raise HTTPException(404, "Instrument not found")
        fs = _resolve_or_http(session, feature_set_code, feature_set_version)
        row = session.scalar(
            select(InstrumentFeatureDaily)
            .where(
                InstrumentFeatureDaily.instrument_id == instrument_id,
                InstrumentFeatureDaily.feature_set_id == fs.id,
            )
            .order_by(desc(InstrumentFeatureDaily.date))
            .limit(1)
        )
        if row is None:
            raise HTTPException(404, "No features calculated for instrument")
        payload = _instrument_feature_dict(row)
        payload["feature_set_code"] = fs.code
        return payload


@router.get("/series/{series_id}/features")
def list_series_features(
    series_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    with core_session() as session:
        filters = [SeriesFeatureDaily.series_id == series_id]
        if date_from:
            filters.append(SeriesFeatureDaily.date >= date_from)
        if date_to:
            filters.append(SeriesFeatureDaily.date <= date_to)
        rows = session.scalars(
            select(SeriesFeatureDaily).where(*filters).order_by(desc(SeriesFeatureDaily.date)).limit(limit)
        ).all()
        items = [
            {
                "id": str(row.id),
                "series_id": str(row.series_id),
                "date": row.date,
                "feature_set_id": str(row.feature_set_id),
                "value": _dec(row.value),
                "previous_value": _dec(row.previous_value),
                "absolute_change": _dec(row.absolute_change),
                "pct_change": _dec(row.pct_change),
                "days_since_change": row.days_since_change,
                "is_valid": row.is_valid,
                "quality_flags": row.quality_flags or {},
                "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
            }
            for row in rows
        ]
        return {"items": items, "total": len(items)}


@router.post("/features/backfill", response_model=WorkflowCreated)
def start_feature_backfill(body: BackfillRequest) -> WorkflowCreated:
    if body.date_to and body.date_to < body.date_from:
        raise HTTPException(400, "date_to must be >= date_from")
    with core_session() as session:
        seed_feature_sets(session)
        workflow = create_workflow(
            session,
            "FeatureBackfill",
            "Feature backfill",
            FEATURE_BACKFILL_STEPS,
        )
        session.commit()
        workflow_id = workflow.id
    worker_tasks.feature_backfill.delay(
        workflow_id,
        body.date_from.isoformat(),
        body.date_to.isoformat() if body.date_to else None,
        body.feature_set_code,
        body.feature_set_version,
    )
    return WorkflowCreated(workflow_id=workflow_id, status="RUNNING")


@router.post("/features/update", response_model=WorkflowCreated)
def start_feature_update(
    feature_set_code: str = "basic_daily",
    feature_set_version: int = 1,
) -> WorkflowCreated:
    with core_session() as session:
        seed_feature_sets(session)
        workflow = create_workflow(
            session,
            "FeatureUpdate",
            "Feature update",
            FEATURE_BACKFILL_STEPS,
        )
        session.commit()
        workflow_id = workflow.id
    worker_tasks.feature_update.delay(workflow_id, feature_set_code, feature_set_version)
    return WorkflowCreated(workflow_id=workflow_id, status="RUNNING")


@router.get("/overview")
def analytics_overview() -> dict[str, Any]:
    """Summary metrics for Analytics UI."""
    with core_session() as session:
        seed_feature_sets(session)
        active = session.scalar(select(FeatureSet).where(FeatureSet.is_active.is_(True)))
        instruments_active = session.scalar(
            select(func.count()).select_from(Instrument).where(Instrument.is_active.is_(True))
        ) or 0
        instrument_rows = 0
        latest_date = None
        if active:
            instrument_rows = (
                session.scalar(
                    select(func.count())
                    .select_from(InstrumentFeatureDaily)
                    .where(InstrumentFeatureDaily.feature_set_id == active.id)
                )
                or 0
            )
            latest_date = session.scalar(
                select(func.max(InstrumentFeatureDaily.date)).where(
                    InstrumentFeatureDaily.feature_set_id == active.id
                )
            )
        last_run = session.scalar(select(FeatureRun).order_by(desc(FeatureRun.created_at)).limit(1))
        quality = {"valid": 0, "invalid": 0, "warnings": 0}
        if active:
            from app.infrastructure.analytics.repository import count_feature_quality

            quality = count_feature_quality(session, active.id)
        instruments_with_features = 0
        if active:
            instruments_with_features = (
                session.scalar(
                    select(func.count(func.distinct(InstrumentFeatureDaily.instrument_id))).where(
                        InstrumentFeatureDaily.feature_set_id == active.id
                    )
                )
                or 0
            )
        return {
            "active_feature_set": _feature_set_dict(active) if active else None,
            "instruments_active": instruments_active,
            "instruments_with_features": instruments_with_features,
            "instrument_feature_rows": instrument_rows,
            "latest_calculated_date": latest_date.isoformat() if latest_date else None,
            "last_feature_run": _feature_run_dict(last_run, active) if last_run else None,
            "quality": quality,
        }
