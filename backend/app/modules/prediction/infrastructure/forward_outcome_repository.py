"""Repository helpers for Forward Outcome Evaluator V0."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.prediction.infrastructure.forward_models import ForwardPrediction, ForwardPredictionBatch
from app.modules.prediction.infrastructure.forward_outcome_models import (
    ForwardBatchEvaluation,
    ForwardPredictionOutcome,
)

EVALUATOR_VERSION = "forward_outcome_v0"
HORIZON = 20


def get_existing_outcome(
    session: Session,
    forward_prediction_id: int,
    *,
    horizon: int = HORIZON,
    version: str = EVALUATOR_VERSION,
) -> ForwardPredictionOutcome | None:
    return session.scalar(
        select(ForwardPredictionOutcome).where(
            ForwardPredictionOutcome.forward_prediction_id == forward_prediction_id,
            ForwardPredictionOutcome.horizon_observations == horizon,
            ForwardPredictionOutcome.evaluator_version == version,
        )
    )


def get_batch_evaluation(
    session: Session,
    batch_id: int,
    *,
    horizon: int = HORIZON,
    version: str = EVALUATOR_VERSION,
) -> ForwardBatchEvaluation | None:
    return session.scalar(
        select(ForwardBatchEvaluation).where(
            ForwardBatchEvaluation.batch_id == batch_id,
            ForwardBatchEvaluation.horizon_observations == horizon,
            ForwardBatchEvaluation.evaluator_version == version,
        )
    )


def list_pending_predictions(session: Session, *, batch_id: int | None = None) -> list[ForwardPrediction]:
    stmt = select(ForwardPrediction).order_by(ForwardPrediction.as_of_date, ForwardPrediction.instrument_id)
    if batch_id is not None:
        stmt = stmt.where(ForwardPrediction.batch_id == batch_id)
    return list(session.scalars(stmt).all())


def list_batches(session: Session) -> list[ForwardPredictionBatch]:
    return list(
        session.scalars(select(ForwardPredictionBatch).order_by(ForwardPredictionBatch.id.asc())).all()
    )


def upsert_outcome_row(session: Session, values: dict[str, Any]) -> tuple[ForwardPredictionOutcome, bool]:
    """Insert outcome if missing. Returns (row, created). Never mutates prediction."""
    existing = get_existing_outcome(
        session,
        int(values["forward_prediction_id"]),
        horizon=int(values.get("horizon_observations", HORIZON)),
        version=str(values.get("evaluator_version", EVALUATOR_VERSION)),
    )
    if existing is not None:
        return existing, False
    row = ForwardPredictionOutcome(**values)
    session.add(row)
    session.flush()
    return row, True


def upsert_batch_evaluation(session: Session, values: dict[str, Any]) -> tuple[ForwardBatchEvaluation, bool]:
    existing = get_batch_evaluation(
        session,
        int(values["batch_id"]),
        horizon=int(values.get("horizon_observations", HORIZON)),
        version=str(values.get("evaluator_version", EVALUATOR_VERSION)),
    )
    if existing is not None:
        # Refresh metrics in place only when status/counts change — keep immutable final EVALUATED.
        if existing.status == "EVALUATED" and values.get("status") == "EVALUATED":
            return existing, False
        for key, val in values.items():
            if key in {"id", "created_at", "batch_id", "evaluator_version", "horizon_observations"}:
                continue
            setattr(existing, key, val)
        session.flush()
        return existing, False
    row = ForwardBatchEvaluation(**values)
    session.add(row)
    session.flush()
    return row, True


def touch_prediction_outcome_status(session: Session, prediction: ForwardPrediction, status: str) -> None:
    """Update only outcome_status linkage field — never predicted_return or ranks."""
    if prediction.outcome_status == status:
        return
    prediction.outcome_status = status
    session.flush()


def serialize_batch_evaluation(row: ForwardBatchEvaluation | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "batch_id": row.batch_id,
        "evaluator_version": row.evaluator_version,
        "horizon_observations": row.horizon_observations,
        "status": row.status,
        "eligible_count": row.eligible_count,
        "evaluated_count": row.evaluated_count,
        "invalid_count": row.invalid_count,
        "pending_count": row.pending_count,
        "mean_predicted": row.mean_predicted,
        "mean_realized": row.mean_realized,
        "mae": row.mae,
        "rmse": row.rmse,
        "directional_accuracy": row.directional_accuracy,
        "spearman_rank_ic": row.spearman_rank_ic,
        "top20_realized_mean": row.top20_realized_mean,
        "bottom20_realized_mean": row.bottom20_realized_mean,
        "top_minus_bottom_spread": row.top_minus_bottom_spread,
        "metrics": row.metrics or {},
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
    }


def serialize_outcome(row: ForwardPredictionOutcome) -> dict[str, Any]:
    evaluated_at = None
    if row.evaluated_at is not None:
        evaluated_at = row.evaluated_at.isoformat()
    return {
        "id": row.id,
        "forward_prediction_id": row.forward_prediction_id,
        "batch_id": row.batch_id,
        "as_of_date": row.as_of_date.isoformat(),
        "instrument_id": row.instrument_id,
        "ticker": row.ticker,
        "horizon_observations": row.horizon_observations,
        "target_date": row.target_date.isoformat() if row.target_date else None,
        "predicted_return_20d": row.predicted_return_20d,
        "realized_return_20d": row.realized_return_20d,
        "prediction_error": row.prediction_error,
        "absolute_error": row.absolute_error,
        "direction_correct": row.direction_correct,
        "mechanical_ca_normalized": row.mechanical_ca_normalized,
        "quality_status": row.quality_status,
        "status": row.status,
        "label_flags": row.label_flags or {},
        "evaluated_at": evaluated_at,
    }
