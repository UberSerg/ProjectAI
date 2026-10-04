"""Paired V3/V4 chronological OOS / ablation / stability campaign.

Research-only wrappers around existing helpers. persist_registry is accepted
only as False. Hyperparameters stay frozen (no Optuna). Ranker payloads must
not expose MAE/RMSE. Ablation masks extra columns to NaN and never drops rows.
Paired deltas are factual bootstrap-by-date comparisons, not a winner verdict.

When ``session`` is provided, the campaign loads a real Dataset V4 ``DatasetRun``
(and optionally proves paired V3/V4 identity). Tests pass synthetic frames.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.modules.learning.dataset_config import feature_names_for_spec_version
from app.modules.prediction.application.research_dataset_loader import load_research_frame
from app.modules.prediction.application.splits import WalkForwardFold
from app.modules.prediction.candidate_config import (
    CANDIDATE_V0_CONFIG,
    RANDOM_SEED,
    CandidateV0Config,
)
from app.modules.research_evidence.ablation import (
    VARIANT_BASE,
    VARIANT_BASE_EVENTS,
    VARIANT_BASE_FUNDAMENTALS,
    VARIANT_V4_FULL,
    run_v4_ablation,
)
from app.modules.research_evidence.oos import (
    EVALUATION_KIND,
    MISSING_FEATURE_POLICY,
    REGRESSION_METRIC_KEYS,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    ResearchOosError,
    assert_no_registry_persist,
    run_chronological_oos,
)
from app.modules.research_evidence.paired_delta import paired_v4_vs_base
from app.modules.research_evidence.pairing import prove_paired_v3_v4
from app.modules.research_evidence.stability import slice_stability

ResearchModelFactory = Callable[[list[str]], Any]

# Ablation variant → paired-delta label (always compared to BASE).
PAIRED_DELTA_SPECS: tuple[tuple[str, str], ...] = (
    ("V4_FULL_vs_BASE", VARIANT_V4_FULL),
    ("FUNDAMENTALS_vs_BASE", VARIANT_BASE_FUNDAMENTALS),
    ("EVENTS_vs_BASE", VARIANT_BASE_EVENTS),
)

_WINNER_WORDING = re.compile(r"\b(winner|winners|wins|champion|champions)\b", re.IGNORECASE)


def _walk_keys(obj: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for key, val in obj.items():
            found.add(str(key))
            found |= _walk_keys(val)
    elif isinstance(obj, list):
        for item in obj:
            found |= _walk_keys(item)
    return found


def _collect_text(obj: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(obj, pd.DataFrame):
        return texts
    if isinstance(obj, dict):
        for key, val in obj.items():
            texts.append(str(key))
            texts.extend(_collect_text(val))
    elif isinstance(obj, list):
        for item in obj:
            texts.extend(_collect_text(item))
    elif isinstance(obj, str):
        texts.append(obj)
    return texts


def assert_no_winner_wording(payload: Any) -> None:
    """Campaign artifacts must not declare a model winner."""
    for text in _collect_text(payload):
        if _WINNER_WORDING.search(text):
            raise ResearchOosError("campaign payload must not use winner wording")


def assert_ranking_metrics_clean(payload: dict[str, Any]) -> None:
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        return
    leaked = REGRESSION_METRIC_KEYS.intersection(_walk_keys(metrics))
    if leaked:
        raise ResearchOosError(f"ranking payload leaked regression keys: {sorted(leaked)}")
    if metrics.get("regression_metrics_skipped") is not True:
        raise ResearchOosError("ranking metrics must skip MAE/RMSE/R²")


def _empty_paired() -> dict[str, Any]:
    empty = {
        "status": STATUS_INSUFFICIENT,
        "method": "bootstrap_trading_dates",
        "n_common_dates": 0,
        "mean_delta": None,
        "ci95_low": None,
        "ci95_high": None,
        "reason": "insufficient_predictions",
    }
    return {
        "status": STATUS_INSUFFICIENT,
        "method": "bootstrap_trading_dates",
        "n_common_dates": 0,
        "ic_delta": empty,
        "top_bucket_realized_return_delta": empty,
        "p_value": None,
        "reason": "insufficient_predictions",
    }


def _predictions(variant_payload: Any) -> pd.DataFrame | None:
    if not isinstance(variant_payload, dict):
        return None
    preds = variant_payload.get("predictions")
    if isinstance(preds, pd.DataFrame) and not preds.empty:
        return preds
    return None


def _paired_delta(
    pred_left: pd.DataFrame | None,
    pred_base: pd.DataFrame | None,
    **kwargs: Any,
) -> dict[str, Any]:
    if pred_left is None or pred_base is None:
        return _empty_paired()
    return paired_v4_vs_base(pred_left, pred_base, **kwargs)


def _resolve_inputs(
    frame: pd.DataFrame | None,
    *,
    session: Session | None,
    v3_run_id: int | None,
    v4_run_id: int | None,
) -> tuple[pd.DataFrame, dict[str, Any] | None, int | None]:
    if session is not None and frame is not None:
        raise ResearchOosError("pass either a synthetic frame or a session, not both")
    pairing: dict[str, Any] | None = None
    loaded_run_id: int | None = None
    if session is not None:
        if v4_run_id is None:
            raise ResearchOosError("v4_run_id is required when session is provided")
        if v3_run_id is not None:
            pairing = prove_paired_v3_v4(session, int(v3_run_id), int(v4_run_id))
        run, loaded = load_research_frame(
            session,
            dataset_spec_version=4,
            dataset_run_id=int(v4_run_id),
        )
        loaded_run_id = int(run.id)
        return loaded, pairing, loaded_run_id
    if frame is None:
        raise ResearchOosError("frame or session+v4_run_id is required")
    if frame.empty:
        raise ResearchOosError("cannot run campaign on an empty frame")
    return frame, pairing, None


def run_paired_v3_v4_evidence_campaign(
    frame: pd.DataFrame | None = None,
    *,
    session: Session | None = None,
    v3_run_id: int | None = None,
    v4_run_id: int | None = None,
    persist_registry: bool = False,
    model_factory: ResearchModelFactory | None = None,
    feature_names: list[str] | None = None,
    folds: list[WalkForwardFold] | list[dict[str, Any]] | None = None,
    development_end_exclusive: date | None = None,
    min_train_n: int = 100,
    min_val_n: int = 20,
    random_seed: int = RANDOM_SEED,
    config: CandidateV0Config = CANDIDATE_V0_CONFIG,
    fold_progress: Callable[..., Any] | None = None,
    variant_progress: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run regression OOS, ranking OOS, V4 ablation, paired deltas, and stability.

    Ablation stays on identical rows/y/folds/seed; extra packs are NaN-masked.
    Paired bootstrap deltas: V4_FULL vs BASE, FUNDAMENTALS vs BASE, EVENTS vs BASE.
    """
    assert_no_registry_persist(persist_registry)
    resolved, pairing, loaded_run_id = _resolve_inputs(
        frame, session=session, v3_run_id=v3_run_id, v4_run_id=v4_run_id
    )
    names = list(feature_names or feature_names_for_spec_version(4))
    shared = {
        "persist_registry": False,
        "model_factory": model_factory,
        "feature_names": names,
        "folds": folds,
        "development_end_exclusive": development_end_exclusive,
        "min_train_n": min_train_n,
        "min_val_n": min_val_n,
        "random_seed": random_seed,
        "config": config,
    }

    def _fold_cb(semantic_name: str):
        def _inner(info: dict[str, Any]) -> None:
            if fold_progress is None:
                return
            payload = dict(info)
            payload["semantic"] = semantic_name
            fold_progress(payload)

        return _inner

    regression = run_chronological_oos(
        resolved, semantic="regression", fold_progress=_fold_cb("regression"), **shared
    )
    ranking = run_chronological_oos(
        resolved, semantic="ranking", fold_progress=_fold_cb("ranking"), **shared
    )
    assert_ranking_metrics_clean(ranking)
    for fold in ranking.get("folds") or []:
        if isinstance(fold, dict):
            assert_ranking_metrics_clean(fold)

    ablation = run_v4_ablation(
        resolved,
        semantic="ranking",
        fold_progress=_fold_cb("ablation"),
        variant_progress=variant_progress,
        **shared,
    )
    for variant_payload in (ablation.get("variants") or {}).values():
        if isinstance(variant_payload, dict):
            assert_ranking_metrics_clean(variant_payload)
            if variant_payload.get("n_rows") != len(resolved):
                raise ResearchOosError("ablation must not drop samples")

    variants = ablation.get("variants") or {}
    pred_base = _predictions(variants.get(VARIANT_BASE))
    paired_deltas: dict[str, Any] = {}
    for label, variant in PAIRED_DELTA_SPECS:
        paired_deltas[label] = _paired_delta(_predictions(variants.get(variant)), pred_base)

    rank_preds = ranking.get("predictions")
    if not isinstance(rank_preds, pd.DataFrame) or rank_preds.empty:
        rank_preds = _predictions(variants.get(VARIANT_V4_FULL))
    if isinstance(rank_preds, pd.DataFrame) and not rank_preds.empty:
        stability = slice_stability(rank_preds, semantic="ranking")
    else:
        stability = {
            "status": STATUS_INSUFFICIENT,
            "slices": {},
            "reason": "insufficient_predictions",
        }

    payload: dict[str, Any] = {
        "label": "PAIRED_V3_V4_EVIDENCE_CAMPAIGN",
        "evaluation_kind": EVALUATION_KIND,
        "persist_registry": False,
        "optuna": False,
        "hyperparameter_search": None,
        "missing_feature_policy": MISSING_FEATURE_POLICY,
        "random_seed": random_seed,
        "same_rows": ablation.get("same_rows"),
        "same_y": ablation.get("same_y"),
        "same_folds": ablation.get("same_folds"),
        "n_rows": int(len(resolved)),
        "dataset_v3_run_id": int(v3_run_id) if v3_run_id is not None else None,
        "dataset_v4_run_id": loaded_run_id if loaded_run_id is not None else (
            int(v4_run_id) if v4_run_id is not None else None
        ),
        "pairing": pairing,
        "regression": regression,
        "ranking": ranking,
        "ablation": ablation,
        "paired_deltas": paired_deltas,
        "stability": stability,
        "note": (
            "CHRONOLOGICAL OOS RESEARCH campaign. Expanding folds with 20d label purge. "
            "Ablation masks V4 packs to NaN and keeps every row. Paired deltas bootstrap "
            "trading dates (V4_FULL/FUNDAMENTALS/EVENTS vs BASE). Factual differences only; "
            "not a production Candidate and not an automatic verdict."
        ),
    }
    statuses = [
        regression.get("status"),
        ranking.get("status"),
        ablation.get("status"),
    ]
    if all(status == STATUS_OK for status in statuses):
        payload["status"] = STATUS_OK
    else:
        payload["status"] = STATUS_INSUFFICIENT
        payload["reason"] = "insufficient_component"
    assert_no_winner_wording(payload)
    return payload
