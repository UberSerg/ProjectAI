"""Market + workflow API schemas and routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.infrastructure.db.session import core_session
from app.infrastructure.market.models import (
    Candle,
    CorporateAction,
    DataQualityIssue,
    IngestionBatch,
    Instrument,
    InstrumentSource,
    Series,
    SeriesValue,
    Workflow,
)
from app.modules.market.application.corporate_actions import SPLIT_INGEST_STEPS
from app.modules.market.application.ingest import BACKFILL_STEPS
from app.modules.market.application.source_windows import WINDOW_SYNC_STEPS
from app.modules.market.application.split_events import SPLIT_FEED_EVENT_TYPES
from app.modules.market.application.workflows import create_workflow
from app.worker import tasks as worker_tasks

router = APIRouter()
workflows_router = APIRouter()


class PageMeta(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


class BackfillRequest(BaseModel):
    symbols: list[str] | None = None
    date_from: date | None = None
    date_to: date | None = None
    default_universe: bool = True


class WorkflowCreated(BaseModel):
    workflow_id: int
    status: str


def _dec(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


@router.get("/instruments")
def list_instruments(
    search: str | None = None,
    asset_class: str | None = None,
    source: str | None = None,
    active: bool | None = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> dict[str, Any]:
    with core_session() as session:
        filters = []
        if active is not None:
            filters.append(Instrument.is_active.is_(active))
        if asset_class:
            filters.append(Instrument.asset_class == asset_class)
        if search:
            pattern = f"%{search}%"
            filters.append((Instrument.symbol.ilike(pattern)) | (Instrument.name.ilike(pattern)))

        base = select(Instrument).where(*filters) if filters else select(Instrument)
        if source:
            base = base.join(InstrumentSource).where(InstrumentSource.source == source)

        total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = session.scalars(
            base.options(selectinload(Instrument.sources))
            .order_by(Instrument.symbol)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).unique().all()

        # Aggregated candle stats in one query
        ids = [row.id for row in rows]
        stats_map: dict[int, dict[str, Any]] = {}
        if ids:
            stats_rows = session.execute(
                select(
                    Candle.instrument_id,
                    func.min(Candle.timestamp),
                    func.max(Candle.timestamp),
                    func.count(Candle.id),
                )
                .where(Candle.instrument_id.in_(ids), Candle.timeframe == "1d")
                .group_by(Candle.instrument_id)
            ).all()
            stats_map = {
                instrument_id: {
                    "first_timestamp": first.isoformat() if first else None,
                    "last_timestamp": last.isoformat() if last else None,
                    "records_count": count,
                }
                for instrument_id, first, last, count in stats_rows
            }

        items = []
        for row in rows:
            st = stats_map.get(row.id, {})
            items.append(
                {
                    "id": str(row.id),
                    "symbol": row.symbol,
                    "name": row.name,
                    "asset_class": row.asset_class,
                    "exchange": row.exchange,
                    "currency": row.currency,
                    "sources": sorted({s.source for s in row.sources}),
                    "first_timestamp": st.get("first_timestamp"),
                    "last_timestamp": st.get("last_timestamp"),
                    "records_count": st.get("records_count", 0),
                    "is_active": row.is_active,
                }
            )
        return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/instruments/{instrument_id}")
def get_instrument(instrument_id: int) -> dict[str, Any]:
    with core_session() as session:
        row = session.scalar(
            select(Instrument)
            .options(selectinload(Instrument.sources))
            .where(Instrument.id == instrument_id)
        )
        if row is None:
            raise HTTPException(404, "Instrument not found")
        first, last, count = session.execute(
            select(func.min(Candle.timestamp), func.max(Candle.timestamp), func.count(Candle.id)).where(
                Candle.instrument_id == instrument_id, Candle.timeframe == "1d"
            )
        ).one()
        last_close = session.scalar(
            select(Candle.close)
            .where(Candle.instrument_id == instrument_id, Candle.timeframe == "1d")
            .order_by(Candle.timestamp.desc())
            .limit(1)
        )
        sources = sorted({s.source for s in row.sources})
        return {
            "id": str(row.id),
            "symbol": row.symbol,
            "name": row.name,
            "asset_class": row.asset_class,
            "exchange": row.exchange,
            "currency": row.currency,
            "isin": row.isin,
            "is_active": row.is_active,
            "sources": sources,
            "mappings": [
                {"source": s.source, "source_symbol": s.external_id, "board": s.board}
                for s in row.sources
            ],
            "first_timestamp": first.isoformat() if first else None,
            "last_timestamp": last.isoformat() if last else None,
            "records_count": count,
            "last_close": _dec(last_close),
        }


@router.get("/instruments/{instrument_id}/candles")
def list_candles(
    instrument_id: int,
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    with core_session() as session:
        rows = session.scalars(
            select(Candle)
            .where(Candle.instrument_id == instrument_id, Candle.timeframe == "1d")
            .order_by(Candle.timestamp.desc())
            .limit(limit)
        ).all()
        items = [
            {
                "timestamp": row.timestamp.isoformat(),
                "open": _dec(row.open),
                "high": _dec(row.high),
                "low": _dec(row.low),
                "close": _dec(row.close),
                "volume": _dec(row.volume),
                "source": row.source,
            }
            for row in rows
        ]
        return {"items": list(reversed(items))}


@router.get("/series")
def list_series() -> dict[str, Any]:
    with core_session() as session:
        rows = session.scalars(select(Series).order_by(Series.code)).all()
        return {
            "items": [
                {
                    "id": str(row.id),
                    "code": row.code,
                    "name": row.name,
                    "unit": row.unit,
                    "source": row.source,
                    "is_active": row.is_active,
                }
                for row in rows
            ]
        }


@router.get("/series/{series_id}/values")
def list_series_values(series_id: int, limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    with core_session() as session:
        rows = session.scalars(
            select(SeriesValue)
            .where(SeriesValue.series_id == series_id)
            .order_by(SeriesValue.timestamp.desc())
            .limit(limit)
        ).all()
        return {
            "items": [
                {
                    "timestamp": row.timestamp.isoformat(),
                    "value": _dec(row.value),
                    "source": row.source,
                }
                for row in reversed(rows)
            ]
        }


@router.get("/batches")
def list_batches(page: int = 1, page_size: int = 25) -> dict[str, Any]:
    with core_session() as session:
        total = session.scalar(select(func.count()).select_from(IngestionBatch)) or 0
        rows = session.scalars(
            select(IngestionBatch)
            .order_by(IngestionBatch.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "items": [
                {
                    "id": str(row.id),
                    "source": row.source,
                    "data_type": row.data_type,
                    "status": row.status,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                    "records_received": row.records_received,
                    "records_inserted": row.records_inserted,
                    "records_updated": row.records_updated,
                    "records_rejected": row.records_rejected,
                    "raw_location": row.raw_location,
                    "error_message": row.error_message,
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int) -> dict[str, Any]:
    with core_session() as session:
        row = session.get(IngestionBatch, batch_id)
        if row is None:
            raise HTTPException(404, "Batch not found")
        return {
            "id": str(row.id),
            "source": row.source,
            "data_type": row.data_type,
            "status": row.status,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "records_received": row.records_received,
            "records_inserted": row.records_inserted,
            "raw_location": row.raw_location,
            "error_message": row.error_message,
        }


@router.get("/data-quality")
def list_data_quality(
    severity: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    with core_session() as session:
        stmt = select(DataQualityIssue)
        if severity:
            stmt = stmt.where(DataQualityIssue.severity == severity)
        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = session.scalars(
            stmt.order_by(DataQualityIssue.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "items": [
                {
                    "id": str(row.id),
                    "instrument_id": str(row.instrument_id) if row.instrument_id else None,
                    "severity": row.severity,
                    "issue_type": row.issue_type,
                    "message": row.message,
                    "detected_at": row.created_at.isoformat(),
                    "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/summary")
def market_summary() -> dict[str, Any]:
    with core_session() as session:
        instruments = session.scalar(select(func.count()).select_from(Instrument)) or 0
        active = session.scalar(
            select(func.count()).select_from(Instrument).where(Instrument.is_active.is_(True))
        ) or 0
        candles = session.scalar(select(func.count()).select_from(Candle)) or 0
        series_count = session.scalar(select(func.count()).select_from(Series)) or 0
        batches = session.scalar(select(func.count()).select_from(IngestionBatch)) or 0
        dq_warnings = session.scalar(
            select(func.count()).select_from(DataQualityIssue).where(DataQualityIssue.severity == "warning")
        ) or 0
        dq_errors = session.scalar(
            select(func.count()).select_from(DataQualityIssue).where(DataQualityIssue.severity == "error")
        ) or 0
        last_success = session.scalar(
            select(func.max(IngestionBatch.finished_at)).where(IngestionBatch.status.in_(["success", "warning"]))
        )
        split_events = session.scalar(
            select(func.count())
            .select_from(CorporateAction)
            .where(CorporateAction.event_type.in_(SPLIT_FEED_EVENT_TYPES))
        ) or 0
        return {
            "instruments_count": instruments,
            "active_instruments_count": active,
            "records_count": candles,
            "series_count": series_count,
            "batches_count": batches,
            "dq_warnings": dq_warnings,
            "dq_errors": dq_errors,
            "last_successful_update": last_success.isoformat() if last_success else None,
            "split_corporate_actions": split_events,
        }


@router.post("/backfill", response_model=WorkflowCreated)
def start_backfill(body: BackfillRequest) -> WorkflowCreated:
    with core_session() as session:
        workflow = create_workflow(
            session,
            "MarketDataBackfill",
            "Market data backfill",
            BACKFILL_STEPS,
        )
        session.commit()
        workflow_id = workflow.id
    worker_tasks.market_data_backfill.delay(
        workflow_id,
        body.symbols if not body.default_universe else body.symbols,
        body.date_from.isoformat() if body.date_from else None,
        body.date_to.isoformat() if body.date_to else None,
    )
    return WorkflowCreated(workflow_id=workflow_id, status="RUNNING")


@router.post("/update", response_model=WorkflowCreated)
def start_update() -> WorkflowCreated:
    with core_session() as session:
        workflow = create_workflow(
            session,
            "MarketDataUpdate",
            "Market data update",
            BACKFILL_STEPS,
        )
        session.commit()
        workflow_id = workflow.id
    worker_tasks.market_data_update.delay(workflow_id)
    return WorkflowCreated(workflow_id=workflow_id, status="RUNNING")


class DataQualityRunRequest(BaseModel):
    mode: Literal["historical", "operational"] = "operational"
    date_from: date | None = None
    date_to: date | None = None


@router.post("/source-windows/sync", response_model=WorkflowCreated)
def start_source_windows_sync() -> WorkflowCreated:
    with core_session() as session:
        workflow = create_workflow(
            session,
            "MarketSourceWindowsSync",
            "MOEX source validity windows",
            WINDOW_SYNC_STEPS,
        )
        session.commit()
        workflow_id = workflow.id
    worker_tasks.market_source_windows_sync.delay(workflow_id)
    return WorkflowCreated(workflow_id=workflow_id, status="RUNNING")


@router.post("/corporate-actions/splits", response_model=WorkflowCreated)
def start_splits_ingest() -> WorkflowCreated:
    with core_session() as session:
        workflow = create_workflow(
            session,
            "MarketSplitsIngest",
            "MOEX SPLIT corporate actions",
            SPLIT_INGEST_STEPS,
        )
        session.commit()
        workflow_id = workflow.id
    worker_tasks.market_splits_ingest.delay(workflow_id)
    return WorkflowCreated(workflow_id=workflow_id, status="RUNNING")


@router.post("/data-quality/run", response_model=WorkflowCreated)
def start_data_quality(body: DataQualityRunRequest | None = None) -> WorkflowCreated:
    payload = body or DataQualityRunRequest()
    with core_session() as session:
        workflow = create_workflow(
            session,
            "DataQualityCheck",
            f"Data quality check ({payload.mode})",
            ["Run Data Quality", "Finish"],
        )
        session.commit()
        workflow_id = workflow.id
    worker_tasks.market_data_quality_run.delay(
        workflow_id,
        payload.mode,
        payload.date_from.isoformat() if payload.date_from else None,
        payload.date_to.isoformat() if payload.date_to else None,
    )
    return WorkflowCreated(workflow_id=workflow_id, status="RUNNING")


def _workflow_payload(row: Workflow) -> dict[str, Any]:
    started = row.started_at
    finished = row.finished_at
    duration = None
    if started and finished:
        duration = int((finished - started).total_seconds())
    return {
        "id": str(row.id),
        "name": row.name,
        "workflow_type": row.workflow_type,
        "status": row.status,
        "started_at": started.isoformat() if started else None,
        "finished_at": finished.isoformat() if finished else None,
        "duration_seconds": duration,
        "error": row.error,
        "meta": row.meta or {},
        "steps": [
            {
                "name": step.name,
                "status": step.status,
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "finished_at": step.finished_at.isoformat() if step.finished_at else None,
                "error": step.error,
            }
            for step in sorted(row.steps, key=lambda s: s.id)
        ],
    }


@workflows_router.get("")
def list_workflows(page: int = 1, page_size: int = 25) -> dict[str, Any]:
    with core_session() as session:
        total = session.scalar(select(func.count()).select_from(Workflow)) or 0
        rows = session.scalars(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .order_by(Workflow.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).unique().all()
        return {
            "items": [_workflow_payload(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@workflows_router.get("/{workflow_id}")
def get_workflow(workflow_id: int) -> dict[str, Any]:
    with core_session() as session:
        row = session.scalar(
            select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.id == workflow_id)
        )
        if row is None:
            raise HTTPException(404, "Workflow not found")
        return _workflow_payload(row)
