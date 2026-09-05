"""Persistence helpers for Forward Signal V0 (immutable predictions)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.prediction.infrastructure.forward_models import (
    ForwardPrediction,
    ForwardPredictionBatch,
)


def lineage_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def batch_prediction_hash(rows: list[dict[str, Any]], *, config_hash: str) -> str:
    """Deterministic hash over ordered prediction rows."""
    lines: list[str] = []
    ordered = sorted(rows, key=lambda r: (r["as_of_date"], int(r["instrument_id"])))
    for r in ordered:
        lines.append(
            f"{r['as_of_date']},{int(r['instrument_id'])},{float(r['predicted_return_20d']):.12g},"
            f"{int(r['rank'])},{config_hash}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def get_latest_success_batch(session: Session) -> ForwardPredictionBatch | None:
    return session.scalar(
        select(ForwardPredictionBatch)
        .where(ForwardPredictionBatch.status == "SUCCESS")
        .order_by(ForwardPredictionBatch.as_of_date.desc(), ForwardPredictionBatch.id.desc())
        .limit(1)
    )


def get_batch(session: Session, batch_id: int) -> ForwardPredictionBatch | None:
    return session.get(ForwardPredictionBatch, batch_id)


def list_batches(
    session: Session,
    *,
    limit: int = 50,
    as_of: Any | None = None,
) -> list[ForwardPredictionBatch]:
    q = select(ForwardPredictionBatch).order_by(
        ForwardPredictionBatch.as_of_date.desc(), ForwardPredictionBatch.id.desc()
    )
    if as_of is not None:
        q = q.where(ForwardPredictionBatch.as_of_date == as_of)
    q = q.limit(limit)
    return list(session.scalars(q))


def get_existing_predictions(
    session: Session,
    *,
    candidate_config_hash: str,
    as_of_date: Any,
) -> list[ForwardPrediction]:
    return list(
        session.scalars(
            select(ForwardPrediction)
            .where(
                ForwardPrediction.candidate_config_hash == candidate_config_hash,
                ForwardPrediction.as_of_date == as_of_date,
            )
            .order_by(ForwardPrediction.instrument_id)
        )
    )


def list_predictions_for_batch(session: Session, batch_id: int) -> list[ForwardPrediction]:
    return list(
        session.scalars(
            select(ForwardPrediction)
            .where(ForwardPrediction.batch_id == batch_id)
            .order_by(ForwardPrediction.rank.nulls_last(), ForwardPrediction.instrument_id)
        )
    )


def create_batch(
    session: Session,
    *,
    as_of_date: Any,
    candidate_name: str,
    candidate_version: str,
    candidate_config_hash: str,
    feature_schema_hash: str,
    dataset_values_hash: str | None,
    segment: str,
    prediction_semantic: str = "EXPECTED_RETURN",
) -> ForwardPredictionBatch:
    from datetime import UTC

    batch = ForwardPredictionBatch(
        as_of_date=as_of_date,
        segment=segment,
        candidate_name=candidate_name,
        candidate_version=candidate_version,
        candidate_config_hash=candidate_config_hash,
        feature_schema_hash=feature_schema_hash,
        dataset_values_hash=dataset_values_hash,
        prediction_semantic=prediction_semantic,
        status="RUNNING",
        started_at=datetime.now(UTC),
    )
    session.add(batch)
    session.flush()
    return batch


def insert_predictions_immutable(
    session: Session,
    *,
    batch: ForwardPredictionBatch,
    rows: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    """Insert predictions. Never overwrite existing unique keys.

    Returns (inserted_count, conflict_notes).
    """
    from datetime import UTC

    notes: list[str] = []
    inserted = 0
    for row in rows:
        existing = session.scalar(
            select(ForwardPrediction).where(
                ForwardPrediction.candidate_config_hash == row["candidate_config_hash"],
                ForwardPrediction.as_of_date == row["as_of_date"],
                ForwardPrediction.instrument_id == row["instrument_id"],
            )
        )
        if existing is not None:
            same = abs(float(existing.predicted_return_20d) - float(row["predicted_return_20d"])) < 1e-12
            if same:
                notes.append(f"EXISTING identical instrument_id={row['instrument_id']}")
            else:
                notes.append(
                    f"FROZEN conflict instrument_id={row['instrument_id']}: "
                    "prediction already frozen; input lineage differs or values changed — not overwritten"
                )
            continue
        session.add(
            ForwardPrediction(
                batch_id=batch.id,
                as_of_date=row["as_of_date"],
                instrument_id=int(row["instrument_id"]),
                ticker=str(row["ticker"]),
                predicted_return_20d=float(row["predicted_return_20d"]),
                rank=int(row["rank"]),
                eligible_count=int(row["eligible_count"]),
                percentile=float(row["percentile"]),
                quality_status=str(row.get("quality_status") or "OK"),
                candidate_config_hash=str(row["candidate_config_hash"]),
                feature_schema_hash=str(row["feature_schema_hash"]),
                input_lineage=dict(row.get("input_lineage") or {}),
                segment=str(row.get("segment") or batch.segment),
                prediction_semantic=str(
                    row.get("prediction_semantic") or batch.prediction_semantic
                ),
                outcome_status=str(row.get("outcome_status") or "PENDING_OUTCOME"),
                generated_at=row.get("generated_at") or datetime.now(UTC),
            )
        )
        inserted += 1
    session.flush()
    return inserted, notes
