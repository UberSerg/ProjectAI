"""Frozen Prediction Candidate V1 Ranker contract (development-only research)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

from app.modules.learning.dataset_config import PIT_DAILY_CORE_CODE, PIT_DAILY_CORE_V2_VERSION
from app.modules.prediction.candidate_config import (
    CANONICAL_DATASET_HASH,
    CANONICAL_DATASET_VALUES_HASH,
    ELIGIBILITY_KEY,
    FEATURE_NAMES,
    HOLDOUT_START,
    LABEL_VALID_HORIZON,
    MIN_IC_INSTRUMENTS,
    MIN_TRAIN_YEARS,
    PREFERRED_DATASET_RUN_ID,
    RANDOM_SEED,
    STEP_MONTHS,
    TARGET_DATE_KEY,
    TARGET_LABEL,
    TOP_BOTTOM_QUANTILE,
    VALIDATION_MONTHS,
)

PredictionSemantic = Literal["RANKING_SCORE"]

# CatBoost YetiRank: ranking loss over query groups; relevance may be real-valued.
# We feed per-date percentile relevance in [0, 1] (relative attractiveness, not return %).
CATBOOST_RANKER_HYPERPARAMETERS: dict[str, Any] = {
    "loss_function": "YetiRank",
    "iterations": 600,
    "depth": 6,
    "learning_rate": 0.05,
    "l2_leaf_reg": 3.0,
    "random_seed": RANDOM_SEED,
    "allow_writing_files": False,
    "task_type": "CPU",
    "thread_count": -1,
}


@dataclass(frozen=True, slots=True)
class CandidateV1RankerConfig:
    """Immutable Candidate V1 Ranker identity — development research only."""

    candidate_name: str = "prediction_ml_candidate"
    candidate_version: str = "v1_ranker"
    model_family: str = "CatBoostRanker"
    prediction_semantic: PredictionSemantic = "RANKING_SCORE"
    human_name: str = "Модель ранжирования V1"
    dataset_spec_code: str = PIT_DAILY_CORE_CODE
    dataset_spec_version: int = PIT_DAILY_CORE_V2_VERSION
    preferred_dataset_run_id: int = PREFERRED_DATASET_RUN_ID
    required_values_hash: str = CANONICAL_DATASET_VALUES_HASH
    required_dataset_hash: str = CANONICAL_DATASET_HASH
    target: str = TARGET_LABEL
    target_date_key: str = TARGET_DATE_KEY
    eligibility_key: str = ELIGIBILITY_KEY
    label_valid_horizon: str = LABEL_VALID_HORIZON
    relevance_transform: str = "cross_sectional_percentile_rank"
    ranking_group: str = "sample_date"
    ranking_objective: str = "YetiRank"
    feature_names: tuple[str, ...] = tuple(FEATURE_NAMES)
    holdout_start: date = HOLDOUT_START
    min_train_years: int = MIN_TRAIN_YEARS
    validation_months: int = VALIDATION_MONTHS
    step_months: int = STEP_MONTHS
    min_ic_instruments: int = MIN_IC_INSTRUMENTS
    top_bottom_quantile: float = TOP_BOTTOM_QUANTILE
    random_seed: int = RANDOM_SEED
    catboost_hyperparameters: dict[str, Any] = field(
        default_factory=lambda: dict(CATBOOST_RANKER_HYPERPARAMETERS)
    )
    bootstrap_date_iterations: int = 1000
    survivorship_disclaimer: str = (
        "Current supported cohort only; survivorship bias present; "
        "not whole-market historical investability. Ranking score ≠ expected return."
    )
    # Explicit: no FINAL_HOLDOUT evaluation for V1 selection in this research stage.
    evaluate_final_holdout: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["holdout_start"] = self.holdout_start.isoformat()
        payload["feature_names"] = list(self.feature_names)
        payload["feature_count"] = len(self.feature_names)
        return payload

    def config_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def feature_schema_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(list(self.feature_names), separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def assert_feature_contract(self) -> None:
        if len(self.feature_names) != 90:
            raise ValueError(f"expected 90 features, got {len(self.feature_names)}")
        if self.feature_names != tuple(FEATURE_NAMES):
            raise ValueError("V1 feature list must match frozen Dataset V2 / V0 feature schema")
        forbidden = (
            "forward_return",
            "target_date",
            "relevance",
            "y_pred",
            "label",
        )
        for name in self.feature_names:
            lower = name.lower()
            if any(tok in lower for tok in forbidden):
                raise ValueError(f"forbidden feature name pattern: {name}")


CANDIDATE_V1_RANKER_CONFIG = CandidateV1RankerConfig()
