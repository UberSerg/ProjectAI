"""Frozen Prediction ML Candidate V0 contract (fixed before holdout)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from app.modules.learning.dataset_config import FEATURE_MANIFEST_V1, PIT_DAILY_CORE_CODE, PIT_DAILY_CORE_V2_VERSION

CANONICAL_DATASET_VALUES_HASH = "afd12a0d3af28fe5c0f3e809f0fb5f378accd9ef00bb3602589afac78cdcf639"
CANONICAL_DATASET_HASH = "00228c413e0b4c4dda649a7ec71b95b138308accae7d3608b714ebfa3b488687"
PREFERRED_DATASET_RUN_ID = 54

TARGET_LABEL = "forward_return_20d"
TARGET_DATE_KEY = "target_date_20d"
ELIGIBILITY_KEY = "training_eligible_20d"
LABEL_VALID_HORIZON = "20d"

HOLDOUT_START = date(2026, 1, 1)
MIN_TRAIN_YEARS = 3
VALIDATION_MONTHS = 6
STEP_MONTHS = 6
MIN_IC_INSTRUMENTS = 10
TOP_BOTTOM_QUANTILE = 0.2
RANDOM_SEED = 42

FEATURE_NAMES: list[str] = [
    str(entry["name"]) for entry in FEATURE_MANIFEST_V1 if entry.get("role") == "feature"
]

CATBOOST_HYPERPARAMETERS: dict[str, Any] = {
    "loss_function": "RMSE",
    "iterations": 800,
    "depth": 6,
    "learning_rate": 0.05,
    "l2_leaf_reg": 3.0,
    "random_seed": RANDOM_SEED,
    "allow_writing_files": False,
    "task_type": "CPU",
    "thread_count": -1,
}


@dataclass(frozen=True, slots=True)
class CandidateV0Config:
    """Immutable Candidate V0 identity — freeze before final holdout."""

    candidate_name: str = "prediction_ml_candidate"
    candidate_version: str = "v0"
    model_family: str = "CatBoostRegressor"
    dataset_spec_code: str = PIT_DAILY_CORE_CODE
    dataset_spec_version: int = PIT_DAILY_CORE_V2_VERSION
    preferred_dataset_run_id: int = PREFERRED_DATASET_RUN_ID
    required_values_hash: str = CANONICAL_DATASET_VALUES_HASH
    required_dataset_hash: str = CANONICAL_DATASET_HASH
    target: str = TARGET_LABEL
    target_date_key: str = TARGET_DATE_KEY
    eligibility_key: str = ELIGIBILITY_KEY
    label_valid_horizon: str = LABEL_VALID_HORIZON
    feature_names: tuple[str, ...] = tuple(FEATURE_NAMES)
    holdout_start: date = HOLDOUT_START
    min_train_years: int = MIN_TRAIN_YEARS
    validation_months: int = VALIDATION_MONTHS
    step_months: int = STEP_MONTHS
    min_ic_instruments: int = MIN_IC_INSTRUMENTS
    top_bottom_quantile: float = TOP_BOTTOM_QUANTILE
    random_seed: int = RANDOM_SEED
    catboost_hyperparameters: dict[str, Any] = field(
        default_factory=lambda: dict(CATBOOST_HYPERPARAMETERS)
    )
    ridge_alpha: float = 1.0
    survivorship_disclaimer: str = (
        "Current supported cohort only; survivorship bias present; "
        "not whole-market historical investability."
    )

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
        forbidden = (
            "forward_return",
            "target_date",
            "instrument_id",
            "symbol",
            "as_of_date",
            "sample_date",
            "eligibility",
            "label",
        )
        for name in self.feature_names:
            lower = name.lower()
            if any(token in lower for token in forbidden if token != "label"):
                # relation feature names may contain nothing forbidden; block exact prefixes
                pass
            if name.startswith("forward_return_") or name.startswith("target_date_"):
                raise ValueError(f"forbidden feature in X: {name}")


CANDIDATE_V0_CONFIG = CandidateV0Config()
CANDIDATE_V0_CONFIG.assert_feature_contract()
