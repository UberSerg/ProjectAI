"""Research-only dataset loader: explicit pit_daily_core v2|v3 without Candidate pins.

Does not mutate Candidate V0/V1 configs. Does not require production hash pins.
Labeled for experimental evaluation only.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetRun, DatasetSampleDaily, DatasetSpec
from app.modules.learning.dataset_config import (
    FEATURE_MANIFEST_V1,
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_V2_VERSION,
    PIT_DAILY_CORE_V3_VERSION,
    feature_names_from_manifest,
)
from app.modules.prediction.candidate_config import (
    ELIGIBILITY_KEY,
    LABEL_VALID_HORIZON,
    TARGET_DATE_KEY,
    TARGET_LABEL,
)

EXPERIMENTAL_V3_RESEARCH = "EXPERIMENTAL_V3_RESEARCH"
ALLOWED_RESEARCH_VERSIONS = frozenset({PIT_DAILY_CORE_V2_VERSION, PIT_DAILY_CORE_V3_VERSION})
FEATURE_NAMES: list[str] = feature_names_from_manifest(FEATURE_MANIFEST_V1)


class ResearchDatasetError(ValueError):
    """Raised when a research dataset load cannot proceed cleanly."""


def resolve_research_dataset_run(
    session: Session,
    *,
    dataset_spec_version: int,
    dataset_run_id: int | None = None,
    dataset_spec_code: str = PIT_DAILY_CORE_CODE,
) -> DatasetRun:
    """Resolve a SUCCESS/WARNING run for explicit research version 2 or 3.

    Unlike Candidate V0 ``resolve_pinned_dataset_run``, this path:
    - accepts version 2 or 3;
    - does not enforce production values_hash / dataset_hash pins;
    - never reads or writes Candidate V0/V1 preferred run IDs.
    """
    if dataset_spec_version not in ALLOWED_RESEARCH_VERSIONS:
        raise ResearchDatasetError(
            f"research loader allows versions {sorted(ALLOWED_RESEARCH_VERSIONS)}, "
            f"got {dataset_spec_version}"
        )
    spec = session.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == dataset_spec_code,
            DatasetSpec.version == dataset_spec_version,
        )
    )
    if spec is None:
        raise ResearchDatasetError(
            f"missing DatasetSpec {dataset_spec_code} v{dataset_spec_version}"
        )
    if dataset_run_id is not None:
        run = session.get(DatasetRun, dataset_run_id)
        if run is None or run.dataset_spec_id != spec.id:
            raise ResearchDatasetError(
                f"run {dataset_run_id} is not {dataset_spec_code}/v{dataset_spec_version}"
            )
        if run.status not in ("SUCCESS", "WARNING"):
            raise ResearchDatasetError(f"run {dataset_run_id} status={run.status}")
        return run
    run = session.scalar(
        select(DatasetRun)
        .where(
            DatasetRun.dataset_spec_id == spec.id,
            DatasetRun.status.in_(("SUCCESS", "WARNING")),
        )
        .order_by(DatasetRun.id.desc())
    )
    if run is None:
        raise ResearchDatasetError(
            f"no SUCCESS/WARNING DatasetRun for {dataset_spec_code}/v{dataset_spec_version}"
        )
    return run


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def load_research_frame(
    session: Session,
    *,
    dataset_spec_version: int,
    dataset_run_id: int | None = None,
    feature_names: list[str] | None = None,
    target: str = TARGET_LABEL,
    target_date_key: str = TARGET_DATE_KEY,
    eligibility_key: str = ELIGIBILITY_KEY,
    label_valid_horizon: str = LABEL_VALID_HORIZON,
) -> tuple[DatasetRun, pd.DataFrame]:
    """Load samples for research evaluation (identical feature schema for v2 and v3)."""
    names = list(feature_names or FEATURE_NAMES)
    run = resolve_research_dataset_run(
        session,
        dataset_spec_version=dataset_spec_version,
        dataset_run_id=dataset_run_id,
    )
    rows = list(
        session.scalars(
            select(DatasetSampleDaily)
            .where(DatasetSampleDaily.dataset_run_id == run.id)
            .order_by(DatasetSampleDaily.as_of_date, DatasetSampleDaily.instrument_id)
        )
    )
    records: list[dict[str, Any]] = []
    for sample in rows:
        features = sample.features or {}
        labels = sample.labels or {}
        label_quality = sample.label_quality or {}
        eligibility = sample.training_eligibility or {}
        label_valid = label_quality.get("label_valid") or {}
        rec: dict[str, Any] = {
            "sample_id": sample.id,
            "instrument_id": sample.instrument_id,
            "as_of_date": sample.as_of_date,
            "y": labels.get(target),
            "target_date_20d": _parse_date(labels.get(target_date_key)),
            "label_valid_20d": bool(label_valid.get(label_valid_horizon)),
            "eligible_20d": bool(eligibility.get(eligibility_key)),
        }
        for name in names:
            val = features.get(name)
            rec[name] = float(val) if val is not None else np.nan
        records.append(rec)
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        raise ResearchDatasetError(f"research run {run.id} has zero samples")
    missing_cols = [c for c in names if c not in frame.columns]
    if missing_cols:
        raise ResearchDatasetError(f"missing feature columns: {missing_cols[:5]}")
    return run, frame


def split_research_oos(
    frame: pd.DataFrame,
    cut: date,
) -> dict[str, Any]:
    """Chronological OOS split with 20d target-boundary purge.

    TRAIN requires: as_of_date < cut AND target_date_20d is not NULL AND
    target_date_20d < cut, plus eligibility/label-valid. OOS is as_of_date >= cut.
    """
    if frame.empty:
        raise ResearchDatasetError("cannot split empty research frame")
    eligible = frame["y"].notna() & frame["label_valid_20d"] & frame["eligible_20d"]
    as_of = pd.to_datetime(frame["as_of_date"])
    target = pd.to_datetime(frame["target_date_20d"], errors="coerce")
    cut_ts = pd.Timestamp(cut)
    pre_cut = eligible & (as_of < cut_ts)
    train_ok = pre_cut & target.notna() & (target < cut_ts)
    oos_ok = eligible & (as_of >= cut_ts)
    purged = pre_cut & ~train_ok
    train_df = frame.loc[train_ok].copy()
    oos_df = frame.loc[oos_ok].copy()
    return {
        "train_df": train_df,
        "oos_df": oos_df,
        "train_n_before_purge": int(pre_cut.sum()),
        "train_n_after_purge": int(train_ok.sum()),
        "purged_train_boundary_rows": int(purged.sum()),
    }
