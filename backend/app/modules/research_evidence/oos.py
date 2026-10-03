"""Chronological walk-forward OOS for Dataset V4 research (not a production Candidate).

Wording is always CHRONOLOGICAL OOS RESEARCH — never a pristine final holdout.
persist_registry is accepted only as False; this path never touches ModelRegistry.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.modules.learning.dataset_config import feature_names_for_spec_version
from app.modules.prediction.application.metrics import (
    cross_sectional_ic,
    evaluate_predictions,
    top_bottom_spread,
)
from app.modules.prediction.application.relevance import (
    cross_sectional_percentile_relevance,
    group_id_codes,
)
from app.modules.prediction.application.research_dataset_loader import (
    EXPERIMENTAL_V4_RESEARCH,
    split_research_oos,
)
from app.modules.prediction.application.splits import (
    WalkForwardFold,
    build_expanding_folds,
)
from app.modules.prediction.candidate_config import (
    CANDIDATE_V0_CONFIG,
    CATBOOST_HYPERPARAMETERS,
    HOLDOUT_START,
    MIN_IC_INSTRUMENTS,
    RANDOM_SEED,
    TOP_BOTTOM_QUANTILE,
    CandidateV0Config,
)

EVALUATION_KIND = "CHRONOLOGICAL OOS RESEARCH"
STATUS_OK = "ok"
STATUS_INSUFFICIENT = "INSUFFICIENT"
MISSING_FEATURE_POLICY = "NATIVE_NAN"
SEMANTIC_REGRESSION = "EXPECTED_RETURN_RESEARCH"
SEMANTIC_RANKING = "RANKING_SCORE"
REGRESSION_METRIC_KEYS = frozenset(
    {"mae", "rmse", "r2", "directional_accuracy", "positive_precision"}
)

ResearchModelFactory = Callable[[list[str]], Any]
SemanticName = Literal["regression", "ranking"]


class ResearchOosError(ValueError):
    """Invalid research OOS contract (registry persist, unknown semantic, empty frame)."""


def assert_no_registry_persist(persist_registry: bool) -> None:
    if persist_registry:
        raise ResearchOosError(
            "CHRONOLOGICAL OOS RESEARCH must not persist production candidate registry rows"
        )


def _feature_matrix(frame: pd.DataFrame, feature_names: list[str]) -> np.ndarray:
    missing = [name for name in feature_names if name not in frame.columns]
    if missing:
        raise ResearchOosError(f"missing feature columns: {missing[:8]}")
    return frame.loc[:, feature_names].to_numpy(dtype=float)


def _call_predict(model: Any, x: np.ndarray) -> np.ndarray:
    if hasattr(model, "predict_many"):
        return np.asarray(model.predict_many(x), dtype=float)
    return np.asarray(model.predict(x), dtype=float)


def _fit_model(model: Any, x: np.ndarray, y: np.ndarray, *, group_id: np.ndarray | None) -> Any:
    if group_id is None:
        model.fit(x, y)
        return model
    try:
        model.fit(x, y, group_id)
    except TypeError:
        model.fit(x, y)
    return model


def _associational_importance(model: Any) -> dict[str, Any] | None:
    if not hasattr(model, "feature_importance"):
        return None
    try:
        values = model.feature_importance()
    except Exception:
        return None
    if not values:
        return None
    return {
        "label": "ASSOCIATIONAL MODEL IMPORTANCE",
        "causal": False,
        "note": "ASSOCIATIONAL MODEL IMPORTANCE — not causal. No SHAP.",
        "values": {str(k): float(v) for k, v in dict(values).items()},
    }


def default_regressor_factory(feature_names: list[str]) -> Any:
    from app.modules.prediction.infrastructure.catboost_adapter import CatBoostRegressorAdapter

    return CatBoostRegressorAdapter(
        model_id=EXPERIMENTAL_V4_RESEARCH,
        model_version="chronological_oos_research",
        hyperparameters=dict(CATBOOST_HYPERPARAMETERS),
        feature_names=list(feature_names),
    )


def default_ranker_factory(feature_names: list[str]) -> Any:
    from app.modules.prediction.candidate_v1_config import CATBOOST_RANKER_HYPERPARAMETERS
    from app.modules.prediction.infrastructure.catboost_ranker_adapter import CatBoostRankerAdapter

    return CatBoostRankerAdapter(
        model_id=EXPERIMENTAL_V4_RESEARCH,
        model_version="chronological_oos_research_ranker",
        hyperparameters=dict(CATBOOST_RANKER_HYPERPARAMETERS),
        feature_names=list(feature_names),
    )


def ranking_metrics(
    frame: pd.DataFrame,
    *,
    min_ic_instruments: int = MIN_IC_INSTRUMENTS,
    top_bottom_quantile: float = TOP_BOTTOM_QUANTILE,
    pred_col: str = "y_pred",
) -> dict[str, Any]:
    """RANKING_SCORE diagnostics only — never MAE/RMSE/R² (score ≠ return %)."""
    ic = cross_sectional_ic(
        frame, min_instruments=min_ic_instruments, pred_col=pred_col, actual_col="y"
    )
    spread = top_bottom_spread(
        frame, quantile=top_bottom_quantile, pred_col=pred_col, actual_col="y"
    )
    positive_share = ic.get("positive_ic_pct")
    if positive_share is not None and positive_share == positive_share:
        positive_share = float(positive_share) / 100.0
    payload = {
        "prediction_semantic": SEMANTIC_RANKING,
        "n": int(len(frame)),
        "rank_ic": ic,
        "median_ic": ic.get("median_ic"),
        "ic_dispersion": ic.get("std_ic"),
        "positive_ic_date_share": positive_share,
        "top_bottom": spread,
        "regression_metrics_skipped": True,
        "regression_metrics_note": (
            "MAE/RMSE/R² and sign accuracy are semantically invalid for RANKING_SCORE. "
            "Never treat rank score as return %."
        ),
    }
    leaked = REGRESSION_METRIC_KEYS.intersection(payload)
    if leaked:
        raise ResearchOosError(f"ranking payload leaked regression keys: {sorted(leaked)}")
    return payload


def regression_metrics_payload(
    frame: pd.DataFrame,
    *,
    min_ic_instruments: int = MIN_IC_INSTRUMENTS,
    top_bottom_quantile: float = TOP_BOTTOM_QUANTILE,
    pred_col: str = "y_pred",
) -> dict[str, Any]:
    """Expected-return-like RESEARCH estimate for target forward_return_20d."""
    metrics = evaluate_predictions(
        frame,
        min_ic_instruments=min_ic_instruments,
        top_bottom_quantile=top_bottom_quantile,
        pred_col=pred_col,
    )
    metrics["prediction_semantic"] = SEMANTIC_REGRESSION
    metrics["n"] = int(len(frame))
    metrics["note"] = (
        "expected-return-like RESEARCH estimate for forward_return_20d; "
        "not a Trading Policy action and not a production Candidate."
    )
    return metrics


def train_val_split_purged(
    frame: pd.DataFrame,
    *,
    validation_start: date,
    validation_end: date,
    config: CandidateV0Config = CANDIDATE_V0_CONFIG,
) -> dict[str, Any]:
    """Train requires as_of < validation_start AND target_date_20d < validation_start.

    Train/purge follow ``split_research_oos``. Validation is that OOS window clipped
    to ``[validation_start, validation_end)``. ``config`` is unused for the split
    itself and kept so callers can share Candidate calendar fields.
    """
    del config
    split = split_research_oos(frame, validation_start)
    train_df = split["train_df"]
    oos_df = split["oos_df"]
    as_of = pd.to_datetime(oos_df["as_of_date"])
    val_df = oos_df.loc[as_of < pd.Timestamp(validation_end)].copy()
    if not train_df.empty:
        train_as_of = pd.to_datetime(train_df["as_of_date"])
        target = pd.to_datetime(train_df["target_date_20d"], errors="coerce")
        cut = pd.Timestamp(validation_start)
        if bool((train_as_of >= cut).any()) or bool((target >= cut).any()) or bool(target.isna().any()):
            raise ResearchOosError("label purge failed: train rows leak into validation_start")
    return {
        "train_df": train_df,
        "val_df": val_df,
        "purged_train_boundary_rows": int(split["purged_train_boundary_rows"]),
        "train_n": int(len(train_df)),
        "val_n": int(len(val_df)),
        "train_n_before_purge": int(split["train_n_before_purge"]),
        "train_n_after_purge": int(split["train_n_after_purge"]),
        "validation_start": validation_start.isoformat(),
        "validation_end": validation_end.isoformat(),
    }


def normalize_folds(
    folds: list[WalkForwardFold] | list[dict[str, Any]] | None,
    frame: pd.DataFrame,
    *,
    development_end_exclusive: date | None = None,
    config: CandidateV0Config = CANDIDATE_V0_CONFIG,
) -> list[WalkForwardFold]:
    if folds:
        out: list[WalkForwardFold] = []
        for i, item in enumerate(folds):
            if isinstance(item, WalkForwardFold):
                out.append(item)
                continue
            val_start = item["validation_start"]
            val_end = item["validation_end"]
            if isinstance(val_start, str):
                val_start = date.fromisoformat(val_start)
            if isinstance(val_end, str):
                val_end = date.fromisoformat(val_end)
            train_start = item.get("train_start")
            train_end = item.get("train_end", val_start)
            if isinstance(train_start, str):
                train_start = date.fromisoformat(train_start)
            if isinstance(train_end, str):
                train_end = date.fromisoformat(train_end)
            if train_start is None:
                as_of = pd.to_datetime(frame["as_of_date"])
                train_start = as_of.min().date()
            out.append(
                WalkForwardFold(
                    fold_id=int(item.get("fold_id", i)),
                    train_start=train_start,
                    train_end=train_end,
                    validation_start=val_start,
                    validation_end=val_end,
                )
            )
        return out
    eligible = frame["y"].notna() & frame["label_valid_20d"] & frame["eligible_20d"]
    if not bool(eligible.any()):
        return []
    data_start = pd.to_datetime(frame.loc[eligible, "as_of_date"]).min().date()
    end = development_end_exclusive or HOLDOUT_START
    return build_expanding_folds(
        data_start=data_start,
        development_end_exclusive=end,
        config=config,
    )


def _fold_payload_base(fold: WalkForwardFold, split: dict[str, Any]) -> dict[str, Any]:
    return {
        "fold_id": fold.fold_id,
        "train_start": fold.train_start.isoformat(),
        "train_end": fold.train_end.isoformat(),
        "validation_start": fold.validation_start.isoformat(),
        "validation_end": fold.validation_end.isoformat(),
        "train_n": split["train_n"],
        "val_n": split["val_n"],
        "purged_train_boundary_rows": split["purged_train_boundary_rows"],
        "split": "expanding_walk_forward",
        "random_split": False,
    }


def run_chronological_oos(
    frame: pd.DataFrame,
    *,
    semantic: SemanticName = "regression",
    feature_names: list[str] | None = None,
    persist_registry: bool = False,
    model_factory: ResearchModelFactory | None = None,
    folds: list[WalkForwardFold] | list[dict[str, Any]] | None = None,
    development_end_exclusive: date | None = None,
    min_train_n: int = 100,
    min_val_n: int = 20,
    min_ic_instruments: int = MIN_IC_INSTRUMENTS,
    top_bottom_quantile: float = TOP_BOTTOM_QUANTILE,
    hyperparameters: dict[str, Any] | None = None,
    random_seed: int = RANDOM_SEED,
    config: CandidateV0Config = CANDIDATE_V0_CONFIG,
) -> dict[str, Any]:
    """Walk-forward expanding OOS with mandatory 20d label purge.

    Dataset rows here are research samples, not a production Candidate pin.
    """
    assert_no_registry_persist(persist_registry)
    if semantic not in ("regression", "ranking"):
        raise ResearchOosError(f"unknown semantic: {semantic}")
    if frame.empty:
        raise ResearchOosError("cannot run chronological OOS on an empty frame")

    names = list(feature_names or feature_names_for_spec_version(4))
    fold_list = normalize_folds(
        folds, frame, development_end_exclusive=development_end_exclusive, config=config
    )
    if hyperparameters is None:
        if semantic == "ranking":
            from app.modules.prediction.candidate_v1_config import CATBOOST_RANKER_HYPERPARAMETERS

            hyperparameters = dict(CATBOOST_RANKER_HYPERPARAMETERS)
        else:
            hyperparameters = dict(CATBOOST_HYPERPARAMETERS)

    factory = model_factory or (
        default_ranker_factory if semantic == "ranking" else default_regressor_factory
    )

    payload: dict[str, Any] = {
        "label": EXPERIMENTAL_V4_RESEARCH,
        "evaluation_kind": EVALUATION_KIND,
        "prediction_semantic": SEMANTIC_RANKING if semantic == "ranking" else SEMANTIC_REGRESSION,
        "target": "forward_return_20d",
        "dataset_spec_version": 4,
        "missing_feature_policy": MISSING_FEATURE_POLICY,
        "persist_registry": False,
        "random_seed": random_seed,
        "hyperparameters": dict(hyperparameters),
        "feature_count": len(names),
        "random_split": False,
        "note": (
            "CHRONOLOGICAL OOS RESEARCH with expanding folds and 20d target purge. "
            "Prediction ≠ Policy. Dataset ≠ production Candidate."
        ),
    }

    if not fold_list:
        payload["status"] = STATUS_INSUFFICIENT
        payload["metrics"] = None
        payload["folds"] = []
        payload["reason"] = "no_walk_forward_folds"
        return payload

    fold_reports: list[dict[str, Any]] = []
    pred_parts: list[pd.DataFrame] = []
    last_importance: dict[str, Any] | None = None

    for fold in fold_list:
        split = train_val_split_purged(
            frame,
            validation_start=fold.validation_start,
            validation_end=fold.validation_end,
            config=config,
        )
        report = _fold_payload_base(fold, split)
        train_df = split["train_df"]
        val_df = split["val_df"]
        if len(train_df) < min_train_n or len(val_df) < min_val_n:
            report["status"] = STATUS_INSUFFICIENT
            report["metrics"] = None
            report["reason"] = "insufficient_samples"
            fold_reports.append(report)
            continue

        train_df = train_df.sort_values(["as_of_date", "instrument_id"], kind="mergesort")
        val_df = val_df.sort_values(["as_of_date", "instrument_id"], kind="mergesort")
        x_train = _feature_matrix(train_df, names)
        x_val = _feature_matrix(val_df, names)
        model = factory(names)
        group_id = None
        y_train = train_df["y"].to_numpy(dtype=float)
        if semantic == "ranking":
            ranked = cross_sectional_percentile_relevance(train_df)
            y_train = ranked["relevance"].to_numpy(dtype=float)
            group_id = group_id_codes(train_df["as_of_date"])
        _fit_model(model, x_train, y_train, group_id=group_id)
        last_importance = _associational_importance(model)
        val_pred = val_df.copy()
        val_pred["y_pred"] = _call_predict(model, x_val)
        val_pred["fold_id"] = fold.fold_id
        if semantic == "ranking":
            metrics = ranking_metrics(
                val_pred,
                min_ic_instruments=min_ic_instruments,
                top_bottom_quantile=top_bottom_quantile,
            )
        else:
            metrics = regression_metrics_payload(
                val_pred,
                min_ic_instruments=min_ic_instruments,
                top_bottom_quantile=top_bottom_quantile,
            )
        report["status"] = STATUS_OK
        report["metrics"] = metrics
        fold_reports.append(report)
        pred_parts.append(val_pred)

    payload["folds"] = fold_reports
    if not pred_parts:
        payload["status"] = STATUS_INSUFFICIENT
        payload["metrics"] = None
        payload["predictions"] = None
        payload["reason"] = "insufficient_samples"
        return payload

    predictions = pd.concat(pred_parts, ignore_index=True)
    if semantic == "ranking":
        overall = ranking_metrics(
            predictions,
            min_ic_instruments=min_ic_instruments,
            top_bottom_quantile=top_bottom_quantile,
        )
    else:
        overall = regression_metrics_payload(
            predictions,
            min_ic_instruments=min_ic_instruments,
            top_bottom_quantile=top_bottom_quantile,
        )
    payload["status"] = STATUS_OK
    payload["metrics"] = overall
    payload["predictions"] = predictions
    if last_importance is not None:
        payload["associational_model_importance"] = last_importance
    return payload


def single_cut_purged_split(frame: pd.DataFrame, cut: date) -> dict[str, Any]:
    """Reuse research_dataset_loader chronological OOS cut (train target_date_20d < cut)."""
    return split_research_oos(frame, cut)
