"""Focused chronological OOS helper for Intelligence Research V1 packs.

Wraps Research Evidence Engine OOS without after-result tuning, without
retuning V4/Canonical Campaign, and without Candidate registry persistence.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd

from app.modules.intelligence.isolation import assert_production_isolation
from app.modules.intelligence.research.constants import (
    EVALUATION_WORDING,
    EXPERIMENT_NAME,
    EXPERIMENT_VERSION,
    MODE_HISTORICAL_EVALUABLE,
    MODEL_SEED,
    PACK_BASE,
)
from app.modules.intelligence.research.coverage import PackCoverageRow
from app.modules.intelligence.research.packs import build_feature_pack
from app.modules.prediction.application.splits import WalkForwardFold
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, CandidateV0Config
from app.modules.research_evidence.oos import (
    EVALUATION_KIND,
    MISSING_FEATURE_POLICY,
    STATUS_INSUFFICIENT,
    SemanticName,
    assert_no_registry_persist,
    run_chronological_oos,
)


class IntelligenceResearchOosError(ValueError):
    """Invalid Intelligence Research OOS request."""


def run_pack_chronological_oos(
    frame: pd.DataFrame,
    *,
    pack_name: str,
    pack_coverage: PackCoverageRow | None = None,
    semantic: SemanticName = "regression",
    persist_registry: bool = False,
    model_factory: Callable[[list[str]], Any] | None = None,
    folds: list[WalkForwardFold] | list[dict[str, Any]] | None = None,
    development_end_exclusive: date | None = None,
    min_train_n: int = 100,
    min_val_n: int = 20,
    random_seed: int = MODEL_SEED,
    config: CandidateV0Config = CANDIDATE_V0_CONFIG,
    fold_progress: Callable[[dict[str, Any]], None] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run Evidence Engine chronological OOS for one historically eligible pack.

    If the pack is not HISTORICAL_EVALUABLE and ``force`` is false, returns an
    INSUFFICIENT envelope instead of inventing a giant campaign.
    """
    assert_production_isolation()
    assert_no_registry_persist(persist_registry)

    pack = build_feature_pack(pack_name)
    if pack_coverage is not None and not force:
        if pack_coverage.evaluation_mode != MODE_HISTORICAL_EVALUABLE:
            return {
                "status": STATUS_INSUFFICIENT,
                "reason": f"pack_not_historical_evaluable:{pack_coverage.evaluation_mode}",
                "evaluation_kind": EVALUATION_KIND,
                "evaluation_wording": EVALUATION_WORDING,
                "experiment_name": EXPERIMENT_NAME,
                "experiment_version": EXPERIMENT_VERSION,
                "pack": pack_name,
                "is_dataset_v5": False,
                "persist_registry": False,
                "after_result_tuning": False,
                "coverage": pack_coverage.to_dict(),
                "note": (
                    "Coverage insufficient for honest chronological OOS; "
                    "see coverage matrix / earliest_honest_known_at."
                ),
            }

    missing_base = [name for name in pack.base_features if name not in frame.columns]
    missing_additive = [name for name in pack.additive_features if name not in frame.columns]
    if missing_base:
        raise IntelligenceResearchOosError(
            f"BASE feature columns missing from frame: {missing_base[:8]}"
        )
    if missing_additive and not force:
        return {
            "status": STATUS_INSUFFICIENT,
            "reason": "additive_feature_columns_absent",
            "missing_columns": missing_additive[:32],
            "evaluation_kind": EVALUATION_KIND,
            "pack": pack_name,
            "is_dataset_v5": False,
            "persist_registry": False,
            "after_result_tuning": False,
        }

    feature_names = list(pack.feature_names) if pack_name != PACK_BASE else list(pack.base_features)
    # When force=True with missing additive cols, use intersection only.
    if force and missing_additive:
        feature_names = [n for n in feature_names if n in frame.columns]

    result = run_chronological_oos(
        frame,
        semantic=semantic,
        feature_names=feature_names,
        persist_registry=False,
        model_factory=model_factory,
        folds=folds,
        development_end_exclusive=development_end_exclusive,
        min_train_n=min_train_n,
        min_val_n=min_val_n,
        random_seed=random_seed,
        config=config,
        fold_progress=fold_progress,
    )
    result = dict(result)
    result.update(
        {
            "artifact_kind": "intelligence_research_pack_oos",
            "experiment_name": EXPERIMENT_NAME,
            "experiment_version": EXPERIMENT_VERSION,
            "pack": pack_name,
            "is_dataset_v5": False,
            "retunes_v4": False,
            "retunes_canonical_campaign": False,
            "after_result_tuning": False,
            "candidate_promotion": False,
            "missing_feature_policy": MISSING_FEATURE_POLICY,
            "feature_names_used": feature_names,
            "evaluation_wording": EVALUATION_WORDING,
        }
    )
    return result
