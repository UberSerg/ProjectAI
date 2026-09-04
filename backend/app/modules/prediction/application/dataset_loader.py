"""Bulk load Dataset V2 samples into a training frame (no N+1)."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetRun, DatasetSampleDaily, DatasetSpec
from app.modules.prediction.candidate_config import CandidateV0Config


class DatasetPinError(ValueError):
    """Raised when Dataset pin / values_hash does not match Candidate V0 contract."""


def resolve_pinned_dataset_run(session: Session, config: CandidateV0Config) -> DatasetRun:
    spec = session.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == config.dataset_spec_code,
            DatasetSpec.version == config.dataset_spec_version,
        )
    )
    if spec is None:
        raise DatasetPinError(
            f"missing DatasetSpec {config.dataset_spec_code} v{config.dataset_spec_version}"
        )
    preferred = session.get(DatasetRun, config.preferred_dataset_run_id)
    if (
        preferred is not None
        and preferred.dataset_spec_id == spec.id
        and preferred.status == "SUCCESS"
    ):
        run = preferred
    else:
        run = session.scalar(
            select(DatasetRun)
            .where(DatasetRun.dataset_spec_id == spec.id, DatasetRun.status == "SUCCESS")
            .order_by(DatasetRun.id.asc())
        )
    if run is None:
        raise DatasetPinError("no SUCCESS DatasetRun for pinned DatasetSpec v2")
    values_hash = (run.manifest or {}).get("values_hash")
    if values_hash != config.required_values_hash:
        raise DatasetPinError(
            f"values_hash mismatch: got {values_hash!r}, "
            f"required {config.required_values_hash!r}"
        )
    if run.dataset_hash != config.required_dataset_hash:
        raise DatasetPinError(
            f"dataset_hash mismatch: got {run.dataset_hash!r}, "
            f"required {config.required_dataset_hash!r}"
        )
    if config.dataset_spec_version != 2:
        raise DatasetPinError("Candidate V0 requires Dataset version 2")
    return run


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def load_candidate_frame(session: Session, config: CandidateV0Config) -> tuple[DatasetRun, pd.DataFrame]:
    """Load all samples for the pinned Dataset V2 run into a flat frame."""
    run = resolve_pinned_dataset_run(session, config)
    rows = list(
        session.scalars(
            select(DatasetSampleDaily)
            .where(DatasetSampleDaily.dataset_run_id == run.id)
            .order_by(DatasetSampleDaily.as_of_date, DatasetSampleDaily.instrument_id)
        )
    )
    feature_names = list(config.feature_names)
    records: list[dict[str, Any]] = []
    for sample in rows:
        features = sample.features or {}
        labels = sample.labels or {}
        label_quality = sample.label_quality or {}
        eligibility = sample.training_eligibility or {}
        label_valid = (label_quality.get("label_valid") or {})
        rec: dict[str, Any] = {
            "sample_id": sample.id,
            "instrument_id": sample.instrument_id,
            "as_of_date": sample.as_of_date,
            "y": labels.get(config.target),
            "target_date_20d": _parse_date(labels.get(config.target_date_key)),
            "label_valid_20d": bool(label_valid.get(config.label_valid_horizon)),
            "eligible_20d": bool(eligibility.get(config.eligibility_key)),
        }
        for name in feature_names:
            val = features.get(name)
            rec[name] = float(val) if val is not None else np.nan
        # Leakage guard: never copy label keys into feature columns
        records.append(rec)
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        raise DatasetPinError("pinned Dataset run has zero samples")
    # Ensure feature order
    missing_cols = [c for c in feature_names if c not in frame.columns]
    if missing_cols:
        raise DatasetPinError(f"missing feature columns: {missing_cols[:5]}")
    return run, frame


def feature_matrix(frame: pd.DataFrame, config: CandidateV0Config) -> np.ndarray:
    return frame.loc[:, list(config.feature_names)].to_numpy(dtype=float)


def assert_no_label_leakage_in_features(config: CandidateV0Config) -> None:
    for name in config.feature_names:
        if name.startswith("forward_return_") or name.startswith("target_date_"):
            raise DatasetPinError(f"label leakage feature: {name}")
