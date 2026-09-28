"""Research-only chronological OOS eval for pit_daily_core v2|v3.

Uses the same CatBoost hyperparameters as Candidate V0 but:
- loads via research_dataset_loader (no production hash pins);
- labels artifacts EXPERIMENTAL_V3_RESEARCH;
- does NOT upsert production Candidate V0/V1 registry rows.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.modules.prediction.application.metrics import evaluate_predictions
from app.modules.prediction.application.research_dataset_loader import (
    EXPERIMENTAL_V3_RESEARCH,
    FEATURE_NAMES,
    load_research_frame,
)
from app.modules.prediction.candidate_config import (
    CATBOOST_HYPERPARAMETERS,
    HOLDOUT_START,
    RANDOM_SEED,
)
from app.modules.prediction.infrastructure.artifacts import write_json
from app.modules.prediction.infrastructure.catboost_adapter import CatBoostRegressorAdapter

# Production Candidate pins must stay untouched.
CANDIDATE_V0_LOCKED_VERSION = 2
CANDIDATE_V1_LOCKED_VERSION = 2


def _feature_matrix(frame: pd.DataFrame, feature_names: list[str]) -> np.ndarray:
    return frame.loc[:, feature_names].to_numpy(dtype=float)


def run_experimental_v2_v3_oos(
    session: Session,
    *,
    dataset_spec_version: int,
    dataset_run_id: int | None = None,
    oos_start: date | None = None,
    artifact_dir: Path | None = None,
    persist_registry: bool = False,
) -> dict[str, Any]:
    """Train on pre-OOS eligible rows, evaluate chronologically on OOS.

    ``persist_registry`` is accepted only as False — production registry writes are
    forbidden on this research path.
    """
    if persist_registry:
        raise ValueError(
            "EXPERIMENTAL_V3_RESEARCH must not persist production candidate registry rows"
        )
    if dataset_spec_version not in (2, 3):
        raise ValueError("dataset_spec_version must be 2 or 3 for research OOS")

    feature_names = list(FEATURE_NAMES)
    run, frame = load_research_frame(
        session,
        dataset_spec_version=dataset_spec_version,
        dataset_run_id=dataset_run_id,
        feature_names=feature_names,
    )
    cut = oos_start or HOLDOUT_START
    eligible = frame["y"].notna() & frame["label_valid_20d"] & frame["eligible_20d"]
    train_df = frame.loc[eligible & (frame["as_of_date"] < cut)].copy()
    oos_df = frame.loc[eligible & (frame["as_of_date"] >= cut)].copy()

    payload: dict[str, Any] = {
        "label": EXPERIMENTAL_V3_RESEARCH,
        "dataset_spec_version": dataset_spec_version,
        "dataset_run_id": run.id,
        "dataset_hash": run.dataset_hash,
        "values_hash": (run.manifest or {}).get("values_hash"),
        "oos_start": cut.isoformat(),
        "train_n": int(len(train_df)),
        "oos_n": int(len(oos_df)),
        "model_family": "CatBoostRegressor",
        "hyperparameters": dict(CATBOOST_HYPERPARAMETERS),
        "random_seed": RANDOM_SEED,
        "candidate_v0_pin_unchanged": CANDIDATE_V0_LOCKED_VERSION == 2,
        "candidate_v1_pin_unchanged": CANDIDATE_V1_LOCKED_VERSION == 2,
        "persist_registry": False,
    }

    if len(train_df) < 100 or len(oos_df) < 20:
        payload["status"] = "insufficient_samples"
        payload["metrics"] = None
        return payload

    model = CatBoostRegressorAdapter(
        model_id=EXPERIMENTAL_V3_RESEARCH,
        model_version=f"v{dataset_spec_version}",
        hyperparameters=dict(CATBOOST_HYPERPARAMETERS),
        feature_names=feature_names,
    )
    model.fit(_feature_matrix(train_df, feature_names), train_df["y"].to_numpy(dtype=float))
    oos_pred = oos_df.copy()
    oos_pred["y_pred"] = model.predict(_feature_matrix(oos_pred, feature_names))
    metrics = evaluate_predictions(
        oos_pred,
        min_ic_instruments=10,
        top_bottom_quantile=0.2,
    )
    payload["status"] = "ok"
    payload["metrics"] = metrics
    payload["note"] = (
        "Research chronological OOS only; not a Candidate promote/rollback decision. "
        "Identical model config across v2|v3 when both runs are evaluated separately."
    )

    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        write_json(artifact_dir / "experimental_oos.json", payload)
        oos_pred[["sample_id", "instrument_id", "as_of_date", "y", "y_pred"]].to_csv(
            artifact_dir / "predictions_oos.csv", index=False
        )
        (artifact_dir / "label.txt").write_text(EXPERIMENTAL_V3_RESEARCH, encoding="utf-8")

    return payload


def compare_experimental_model_v2_v3(
    session: Session,
    *,
    v2_run_id: int | None = None,
    v3_run_id: int | None = None,
    oos_start: date | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Run identical-config OOS on V2 and V3 research runs; factual side-by-side only."""
    root = artifact_root
    v2 = run_experimental_v2_v3_oos(
        session,
        dataset_spec_version=2,
        dataset_run_id=v2_run_id,
        oos_start=oos_start,
        artifact_dir=(root / "v2") if root else None,
    )
    v3 = run_experimental_v2_v3_oos(
        session,
        dataset_spec_version=3,
        dataset_run_id=v3_run_id,
        oos_start=oos_start,
        artifact_dir=(root / "v3") if root else None,
    )
    out = {
        "label": EXPERIMENTAL_V3_RESEARCH,
        "artifact_kind": "v2_v3_model_research_oos",
        "v2": v2,
        "v3": v3,
        "interpretation": [
            "Same CatBoost hyperparameters and chronological OOS cut for both sides.",
            "Differences may reflect universe composition, not a claim that one dataset 'wins'.",
            "Production Candidate V0/V1 remain pinned to Dataset V2; ACTIVE DatasetSpec unchanged.",
            "No production model_registry upsert on this path.",
        ],
    }
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        write_json(root / "model_compare.json", out)
    return out
