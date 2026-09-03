"""Batch persistence for dataset samples."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetSampleDaily


def insert_dataset_samples(session: Session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    # Immutable runs: plain insert (unique per run+instrument+date)
    session.bulk_insert_mappings(DatasetSampleDaily, rows)
    session.flush()
    return len(rows)


def sample_row(
    *,
    dataset_run_id: int,
    dataset_spec_id: UUID,
    instrument_id: int,
    as_of_date: Any,
    features: dict[str, Any],
    labels: dict[str, Any],
    feature_quality: dict[str, Any],
    label_quality: dict[str, Any],
    training_eligibility: dict[str, Any],
    lineage: dict[str, Any],
    content_hash: str,
) -> dict[str, Any]:
    return {
        "dataset_run_id": dataset_run_id,
        "dataset_spec_id": dataset_spec_id,
        "instrument_id": instrument_id,
        "as_of_date": as_of_date,
        "features": features,
        "labels": labels,
        "feature_quality": feature_quality,
        "label_quality": label_quality,
        "training_eligibility": training_eligibility,
        "lineage": lineage,
        "content_hash": content_hash,
        "created_at": datetime.now(UTC),
    }
