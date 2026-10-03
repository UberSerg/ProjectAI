"""Research-only chronological OOS eval for pit_daily_core v2|v3.

Uses the same CatBoost hyperparameters as Candidate V0 but:
- loads via research_dataset_loader (no production hash pins);
- purges TRAIN rows whose 20d target reaches/crosses the OOS cut;
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

from app.infrastructure.learning.models import DatasetSpec
from app.modules.learning.application.research_eval import (
    FairCompareError,
    assert_fair_model_run_contract,
    assert_fair_v3_v4_model_run_contract,
)
from app.modules.learning.dataset_config import feature_names_for_spec_version
from app.modules.prediction.application.metrics import evaluate_predictions
from app.modules.prediction.application.research_dataset_loader import (
    EXPERIMENTAL_V3_RESEARCH,
    EXPERIMENTAL_V4_RESEARCH,
    V3_V4_FEATURE_ENRICHMENT_RESEARCH,
    load_research_frame,
    resolve_research_dataset_run,
    split_research_oos,
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


class ResearchCompareError(FairCompareError):
    """Raised when experimental V2↔V3 model compare is not a fair experiment."""


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
    """Train on pre-OOS eligible rows (purged 20d target), evaluate on OOS.

    ``persist_registry`` is accepted only as False — production registry writes are
    forbidden on this research path.
    """
    if persist_registry:
        raise ValueError(
            "experimental research OOS must not persist production candidate registry rows"
        )
    if dataset_spec_version not in (2, 3, 4):
        raise ValueError("dataset_spec_version must be 2, 3 or 4 for research OOS")

    feature_names = list(feature_names_for_spec_version(dataset_spec_version))
    label = EXPERIMENTAL_V4_RESEARCH if dataset_spec_version == 4 else EXPERIMENTAL_V3_RESEARCH
    run, frame = load_research_frame(
        session,
        dataset_spec_version=dataset_spec_version,
        dataset_run_id=dataset_run_id,
        feature_names=feature_names,
    )
    cut = oos_start or HOLDOUT_START
    if run.date_from is not None and run.date_to is not None:
        if cut < run.date_from or cut > run.date_to:
            raise ResearchCompareError(
                f"oos_start {cut.isoformat()} is outside run {run.id} "
                f"{run.date_from}→{run.date_to}"
            )
    split = split_research_oos(frame, cut)
    train_df = split["train_df"]
    oos_df = split["oos_df"]

    payload: dict[str, Any] = {
        "label": label,
        "dataset_spec_version": dataset_spec_version,
        "dataset_run_id": run.id,
        "dataset_hash": run.dataset_hash,
        "values_hash": (run.manifest or {}).get("values_hash"),
        "date_from": run.date_from.isoformat() if run.date_from else None,
        "date_to": run.date_to.isoformat() if run.date_to else None,
        "oos_start": cut.isoformat(),
        "train_n_before_purge": split["train_n_before_purge"],
        "purged_train_boundary_rows": split["purged_train_boundary_rows"],
        "train_n_after_purge": split["train_n_after_purge"],
        "train_n": int(len(train_df)),
        "oos_n": int(len(oos_df)),
        "model_family": "CatBoostRegressor",
        "hyperparameters": dict(CATBOOST_HYPERPARAMETERS),
        "random_seed": RANDOM_SEED,
        "candidate_v0_pin_unchanged": CANDIDATE_V0_LOCKED_VERSION == 2,
        "candidate_v1_pin_unchanged": CANDIDATE_V1_LOCKED_VERSION == 2,
        "persist_registry": False,
        "missing_feature_policy": "NATIVE_NAN",
        "feature_count": len(feature_names),
    }

    if len(train_df) < 100 or len(oos_df) < 20:
        payload["status"] = "insufficient_samples"
        payload["metrics"] = None
        return payload

    model = CatBoostRegressorAdapter(
        model_id=label,
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
        "TRAIN excludes rows whose target_date_20d is NULL or >= oos_start. "
        "Identical model config across v2|v3 when compared under assert_fair_model_run_contract."
    )

    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        write_json(artifact_dir / "experimental_oos.json", payload)
        oos_pred[["sample_id", "instrument_id", "as_of_date", "y", "y_pred"]].to_csv(
            artifact_dir / "predictions_oos.csv", index=False
        )
        (artifact_dir / "label.txt").write_text(label, encoding="utf-8")

    return payload


def compare_experimental_model_v2_v3(
    session: Session,
    *,
    v2_run_id: int | None = None,
    v3_run_id: int | None = None,
    oos_start: date | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Run identical-config OOS on V2 and V3 only when the fair contract holds."""
    cut = oos_start or HOLDOUT_START
    run_v2 = resolve_research_dataset_run(session, dataset_spec_version=2, dataset_run_id=v2_run_id)
    run_v3 = resolve_research_dataset_run(session, dataset_spec_version=3, dataset_run_id=v3_run_id)
    spec_v2 = session.get(DatasetSpec, run_v2.dataset_spec_id)
    spec_v3 = session.get(DatasetSpec, run_v3.dataset_spec_id)
    try:
        fair = assert_fair_model_run_contract(
            run_v2,
            run_v3,
            oos_start=cut,
            hyperparameters=dict(CATBOOST_HYPERPARAMETERS),
            random_seed=RANDOM_SEED,
            spec_v2=spec_v2,
            spec_v3=spec_v3,
        )
    except FairCompareError as exc:
        raise ResearchCompareError(str(exc)) from exc

    root = artifact_root
    v2 = run_experimental_v2_v3_oos(
        session,
        dataset_spec_version=2,
        dataset_run_id=run_v2.id,
        oos_start=cut,
        artifact_dir=(root / "v2") if root else None,
    )
    v3 = run_experimental_v2_v3_oos(
        session,
        dataset_spec_version=3,
        dataset_run_id=run_v3.id,
        oos_start=cut,
        artifact_dir=(root / "v3") if root else None,
    )
    out = {
        "label": EXPERIMENTAL_V3_RESEARCH,
        "artifact_kind": "v2_v3_model_research_oos",
        "fair_contract_pass": True,
        "fair_compare": fair,
        "oos_start": cut.isoformat(),
        "hyperparameters": dict(CATBOOST_HYPERPARAMETERS),
        "random_seed": RANDOM_SEED,
        "v2": v2,
        "v3": v3,
        "persist_registry": False,
        "interpretation": [
            "Same CatBoost hyperparameters, seed, chronological OOS cut, and run windows.",
            "TRAIN labels whose target_date_20d reaches or crosses oos_start are purged.",
            "Differences may reflect universe composition, not a claim that one dataset 'wins'.",
            "Production Candidate V0/V1 remain pinned to Dataset V2; ACTIVE DatasetSpec unchanged.",
            "No production model_registry upsert on this path.",
        ],
    }
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        write_json(root / "model_compare.json", out)
    return out


def compare_experimental_model_v3_v4(
    session: Session,
    *,
    v3_run_id: int | None = None,
    v4_run_id: int | None = None,
    oos_start: date | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Identical-config chronological OOS; V4 differs only by feature manifest."""
    cut = oos_start or HOLDOUT_START
    run_v3 = resolve_research_dataset_run(session, dataset_spec_version=3, dataset_run_id=v3_run_id)
    run_v4 = resolve_research_dataset_run(session, dataset_spec_version=4, dataset_run_id=v4_run_id)
    spec_v3 = session.get(DatasetSpec, run_v3.dataset_spec_id)
    spec_v4 = session.get(DatasetSpec, run_v4.dataset_spec_id)
    try:
        fair = assert_fair_v3_v4_model_run_contract(
            run_v3,
            run_v4,
            oos_start=cut,
            hyperparameters=dict(CATBOOST_HYPERPARAMETERS),
            random_seed=RANDOM_SEED,
            spec_v3=spec_v3,
            spec_v4=spec_v4,
        )
    except FairCompareError as exc:
        raise ResearchCompareError(str(exc)) from exc

    root = artifact_root
    v3 = run_experimental_v2_v3_oos(
        session,
        dataset_spec_version=3,
        dataset_run_id=run_v3.id,
        oos_start=cut,
        artifact_dir=(root / "v3") if root else None,
    )
    v4 = run_experimental_v2_v3_oos(
        session,
        dataset_spec_version=4,
        dataset_run_id=run_v4.id,
        oos_start=cut,
        artifact_dir=(root / "v4") if root else None,
    )
    out = {
        "label": V3_V4_FEATURE_ENRICHMENT_RESEARCH,
        "artifact_kind": "v3_v4_model_research_oos",
        "fair_contract_pass": True,
        "fair_compare": fair,
        "oos_start": cut.isoformat(),
        "hyperparameters": dict(CATBOOST_HYPERPARAMETERS),
        "random_seed": RANDOM_SEED,
        "missing_feature_policy": "NATIVE_NAN",
        "v3": v3,
        "v4": v4,
        "feature_delta": {
            "v3_feature_count": fair.get("v3_feature_count"),
            "v4_feature_count": fair.get("v4_feature_count"),
            "added_features": fair.get("added_features"),
        },
        "persist_registry": False,
        "interpretation": [
            "Same CatBoost hyperparameters, seed, chronological OOS cut, universe, and labels.",
            "Intended difference is V4 PIT fundamental/event features; missing values stay NaN.",
            "TRAIN labels whose target_date_20d reaches or crosses oos_start are purged.",
            "This is EXPERIMENTAL_V4_RESEARCH / V3_V4_FEATURE_ENRICHMENT_RESEARCH — not Candidate.",
            "Production Candidate V0/V1 remain pinned to Dataset V2; ACTIVE DatasetSpec unchanged.",
            "No production model_registry upsert on this path.",
        ],
    }
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        write_json(root / "model_compare.json", out)
    return out
