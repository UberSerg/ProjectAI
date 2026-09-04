"""Read-only Forward Signal V0 API."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.infrastructure.db.session import core_session
from app.modules.market.application.workflows import create_workflow
from app.modules.prediction.application.forward_config import FORWARD_SEGMENT
from app.modules.prediction.infrastructure import forward_repository as repo
from app.modules.prediction.infrastructure.forward_models import ForwardPrediction, ForwardPredictionBatch
from app.worker import tasks as worker_tasks

router = APIRouter()


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


class ForwardBatchSummary(BaseModel):
    id: str
    as_of_date: date
    segment: str
    status: str
    candidate_name: str
    candidate_version: str
    candidate_config_hash: str
    feature_schema_hash: str
    prediction_hash: str | None
    eligible_count: int
    ineligible_count: int
    prediction_count: int
    pit_status: str
    generated_at: str | None
    completed_at: str | None


class ForwardPredictionItem(BaseModel):
    instrument_id: int
    ticker: str
    as_of_date: date
    predicted_return_20d: float
    rank: int | None
    eligible_count: int | None
    percentile: float | None
    quality_status: str
    outcome_status: str
    candidate_config_hash: str
    generated_at: str | None


class ForwardBatchDetail(BaseModel):
    batch: ForwardBatchSummary
    predictions: list[ForwardPredictionItem]
    input_lineage: dict[str, Any] | None = None
    completeness: dict[str, Any] | None = None
    timings: dict[str, Any] | None = None


def _batch_summary(b: ForwardPredictionBatch) -> ForwardBatchSummary:
    return ForwardBatchSummary(
        id=str(b.id),
        as_of_date=b.as_of_date,
        segment=b.segment,
        status=b.status,
        candidate_name=b.candidate_name,
        candidate_version=b.candidate_version,
        candidate_config_hash=b.candidate_config_hash,
        feature_schema_hash=b.feature_schema_hash,
        prediction_hash=b.prediction_hash,
        eligible_count=b.eligible_count,
        ineligible_count=b.ineligible_count,
        prediction_count=b.prediction_count,
        pit_status=b.pit_status,
        generated_at=_dt(b.generated_at),
        completed_at=_dt(b.completed_at),
    )


def _pred_item(p: ForwardPrediction) -> ForwardPredictionItem:
    return ForwardPredictionItem(
        instrument_id=int(p.instrument_id),
        ticker=p.ticker,
        as_of_date=p.as_of_date,
        predicted_return_20d=float(p.predicted_return_20d),
        rank=p.rank,
        eligible_count=p.eligible_count,
        percentile=p.percentile,
        quality_status=p.quality_status,
        outcome_status=p.outcome_status,
        candidate_config_hash=p.candidate_config_hash,
        generated_at=_dt(p.generated_at),
    )


@router.get("/forward/latest", response_model=ForwardBatchDetail)
def get_latest_forward_batch() -> ForwardBatchDetail:
    with core_session() as session:
        batch = repo.get_latest_success_batch(session)
        if batch is None:
            raise HTTPException(status_code=404, detail="No SUCCESS forward prediction batch")
        preds = repo.list_predictions_for_batch(session, batch.id)
        return ForwardBatchDetail(
            batch=_batch_summary(batch),
            predictions=[_pred_item(p) for p in preds],
            input_lineage=batch.input_lineage,
            completeness=batch.completeness,
            timings=batch.timings,
        )


@router.get("/forward", response_model=list[ForwardBatchSummary])
def list_forward_batches(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    as_of: date | None = None,
) -> list[ForwardBatchSummary]:
    with core_session() as session:
        batches = repo.list_batches(session, limit=limit, as_of=as_of)
        return [_batch_summary(b) for b in batches]


@router.get("/forward/{batch_id}", response_model=ForwardBatchDetail)
def get_forward_batch(batch_id: int) -> ForwardBatchDetail:
    with core_session() as session:
        batch = repo.get_batch(session, batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Forward batch not found")
        preds = repo.list_predictions_for_batch(session, batch.id)
        return ForwardBatchDetail(
            batch=_batch_summary(batch),
            predictions=[_pred_item(p) for p in preds],
            input_lineage=batch.input_lineage,
            completeness=batch.completeness,
            timings=batch.timings,
        )


@router.post("/forward/run")
def enqueue_forward_signal(as_of: date | None = None) -> dict[str, Any]:
    """Manual operator trigger — creates workflow + Celery task (not auto-scheduled)."""
    with core_session() as session:
        workflow = create_workflow(
            session,
            "BuildForwardSignalLatest",
            f"Forward Signal V0 ({as_of.isoformat() if as_of else 'latest'})",
            [
                "Load frozen Candidate V0",
                "Select complete as_of",
                "Check upstream readiness",
                "Assemble PIT features",
                "Infer predictions",
                "Persist immutable batch",
                "Finish",
            ],
        )
        session.commit()
        workflow_id = workflow.id
    async_result = worker_tasks.build_forward_signal_latest.delay(
        workflow_id, as_of.isoformat() if as_of else None
    )
    return {
        "workflow_id": workflow_id,
        "task_id": async_result.id,
        "segment": FORWARD_SEGMENT,
        "as_of": as_of.isoformat() if as_of else None,
    }
