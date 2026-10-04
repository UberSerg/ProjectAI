"""Frozen Canonical Evidence Campaign V1 identity.

Runtime timestamps are metadata only and never enter the fingerprint.
Does not train models and does not activate DatasetSpec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.modules.market.application.historical_universe import HISTORICAL_EQUITY_UNIVERSE_V2
from app.modules.prediction.candidate_config import (
    CATBOOST_HYPERPARAMETERS,
    MIN_TRAIN_YEARS,
    RANDOM_SEED,
    STEP_MONTHS,
    TARGET_LABEL,
    VALIDATION_MONTHS,
)
from app.modules.prediction.candidate_v1_config import CATBOOST_RANKER_HYPERPARAMETERS
from app.modules.research_evidence.ablation import ABLATION_VARIANTS
from app.modules.research_evidence.experiment import fingerprint_identity

# Frozen fingerprint identity. Public API/UI maps this to CanonicalEvidenceCampaignV1
# (see campaign_runner.PUBLIC_CAMPAIGN_VERSION). Do not swap the two: changing this
# string would rewrite campaign fingerprints.
CAMPAIGN_VERSION = "canonical_evidence_campaign_v1"
PRIMARY_TARGET = TARGET_LABEL
PRIMARY_WINDOW_START = date(2022, 4, 1)
PRIMARY_REBALANCE_SESSIONS = 20
PRIMARY_TOP_PERCENT = 20
PRIMARY_COST_BPS_PER_SIDE = 30
COST_BPS_GRID: tuple[int, ...] = (0, 10, 30, 50)
REBALANCE_SESSIONS_GRID: tuple[int, ...] = (10, 20, 40)
TOP_PERCENT_GRID: tuple[int, ...] = (10, 20, 30)
EVALUATION_END_POLICY = "CAMPAIGN_DATE_TO_INCLUSIVE"
# First COMPLETE dossier evaluated OOS only to Candidate HOLDOUT_START. Immutable audit.
SUPERSEDED_CAMPAIGN_FINGERPRINTS: dict[str, str] = {
    "caf1d5703aae7c2c008015e82cc1086cf68d0fa71f138eb05eb39bec2a25cd75": "OOS_EVALUATION_BOUNDARY_MISMATCH",
}


def frozen_catboost_config_hash(hyperparameters: dict[str, Any]) -> str:
    """SHA-256 of frozen CatBoost hypers (not the full Candidate V0/V1 pin)."""
    return fingerprint_identity(dict(hyperparameters))


def regression_model_config_hash() -> str:
    return frozen_catboost_config_hash(CATBOOST_HYPERPARAMETERS)


def ranker_model_config_hash() -> str:
    return frozen_catboost_config_hash(CATBOOST_RANKER_HYPERPARAMETERS)


def default_walk_forward_contract() -> dict[str, Any]:
    """Predeclared expanding walk-forward (same pins as chronological OOS research)."""
    return {
        "holdout_wording": "CHRONOLOGICAL OOS RESEARCH",
        "kind": "expanding_walk_forward",
        "label_purge": {
            "as_of_date_lt_validation_start": True,
            "target_date_20d_lt_validation_start": True,
        },
        "min_train_years": MIN_TRAIN_YEARS,
        "optuna": False,
        "predeclared_primary_start": PRIMARY_WINDOW_START.isoformat(),
        "random_split": False,
        "step_months": STEP_MONTHS,
        "target_horizon_sessions": 20,
        "validation_months": VALIDATION_MONTHS,
        "evaluation_end_policy": EVALUATION_END_POLICY,
    }


def default_ablation_variants() -> list[str]:
    return list(ABLATION_VARIANTS)


def default_economic_primary_contract() -> dict[str, Any]:
    """PREDECLARED primary economics: ranking V4_FULL, 20 sessions, top 20%, 30 bps/side."""
    return {
        "benchmark": "eligible_universe_equal_weight",
        "cost_assumption": "ASSUMED_ALL_IN_COST_BPS_PER_SIDE",
        "cost_bps_per_side": PRIMARY_COST_BPS_PER_SIDE,
        "dividends": "excluded",
        "execution": "next_open",
        "leverage": False,
        "model_semantic": "RANKING",
        "portfolio": "long_only",
        "position_sizing": "FRACTIONAL_RESEARCH_WEIGHTS",
        "rebalance_sessions": PRIMARY_REBALANCE_SESSIONS,
        "return_semantic": "PRICE_RETURN",
        "shorts": False,
        "signal": "eod_T",
        "top_percent": PRIMARY_TOP_PERCENT,
        "variant": "V4_FULL",
    }


def default_robustness_matrix_contract() -> dict[str, Any]:
    """PREDECLARED robustness grid. Not a hyperparameter search; primary cell is fixed."""
    return {
        "cost_bps_per_side": list(COST_BPS_GRID),
        "kind": "PREDECLARED_ROBUSTNESS_MATRIX",
        "not_hyperparameter_search": True,
        "primary": {
            "cost_bps_per_side": PRIMARY_COST_BPS_PER_SIDE,
            "rebalance_sessions": PRIMARY_REBALANCE_SESSIONS,
            "top_percent": PRIMARY_TOP_PERCENT,
        },
        "rebalance_sessions": list(REBALANCE_SESSIONS_GRID),
        "top_percent": list(TOP_PERCENT_GRID),
    }


def _iso_date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


@dataclass(frozen=True, slots=True)
class CanonicalEvidenceCampaignV1:
    """Deterministic paired V3/V4 campaign contract (identity ≠ runtime)."""

    dataset_v3_run_id: int
    dataset_v4_run_id: int
    dataset_v3_hash: str
    dataset_v4_hash: str
    date_from: date | str
    date_to: date | str
    dataset_v3_values_hash: str | None = None
    dataset_v4_values_hash: str | None = None
    data_snapshot_hash: str | None = None
    model_seed: int = RANDOM_SEED
    persist_registry: bool = False
    created_at: datetime | str | None = None
    historical_universe_version: str = HISTORICAL_EQUITY_UNIVERSE_V2
    walk_forward_contract: dict[str, Any] = field(default_factory=default_walk_forward_contract)
    ablation_variants: list[str] = field(default_factory=default_ablation_variants)
    economic_primary_contract: dict[str, Any] = field(
        default_factory=default_economic_primary_contract
    )
    robustness_matrix_contract: dict[str, Any] = field(
        default_factory=default_robustness_matrix_contract
    )
    regression_config_hash: str = field(default_factory=regression_model_config_hash)
    ranker_config_hash: str = field(default_factory=ranker_model_config_hash)

    def __post_init__(self) -> None:
        if self.persist_registry is True:
            raise ValueError(
                "persist_registry must be false: campaign must not mutate "
                "the production candidate registry"
            )
        if self.persist_registry is not False:
            raise ValueError("persist_registry must be false")
        if self.historical_universe_version != HISTORICAL_EQUITY_UNIVERSE_V2:
            raise ValueError(
                "campaign universe must be historical_equity_universe_v2 "
                f"(got {self.historical_universe_version!r})"
            )
        object.__setattr__(self, "date_from", _iso_date(self.date_from))
        object.__setattr__(self, "date_to", _iso_date(self.date_to))
        date_to = date.fromisoformat(str(self.date_to))
        walk = {**default_walk_forward_contract(), **dict(self.walk_forward_contract)}
        walk["evaluation_end_policy"] = EVALUATION_END_POLICY
        walk["evaluation_end_inclusive"] = date_to.isoformat()
        walk["development_end_exclusive"] = (date_to + timedelta(days=1)).isoformat()
        object.__setattr__(self, "walk_forward_contract", walk)

    def identity_payload(self) -> dict[str, Any]:
        """Canonical frozen fields. Dict insertion order does not affect the hash."""
        return {
            "ablation_variants": list(self.ablation_variants),
            "campaign_version": CAMPAIGN_VERSION,
            "data_snapshot_hash": self.data_snapshot_hash,
            "dataset_v3_hash": self.dataset_v3_hash,
            "dataset_v3_run_id": int(self.dataset_v3_run_id),
            "dataset_v3_values_hash": self.dataset_v3_values_hash,
            "dataset_v4_hash": self.dataset_v4_hash,
            "dataset_v4_run_id": int(self.dataset_v4_run_id),
            "dataset_v4_values_hash": self.dataset_v4_values_hash,
            "date_from": _iso_date(self.date_from),
            "date_to": _iso_date(self.date_to),
            "economic_primary_contract": dict(self.economic_primary_contract),
            "historical_universe_version": HISTORICAL_EQUITY_UNIVERSE_V2,
            "model_seed": int(self.model_seed),
            "persist_registry": False,
            "primary_target": PRIMARY_TARGET,
            "ranker_config_hash": self.ranker_config_hash,
            "regression_config_hash": self.regression_config_hash,
            "robustness_matrix_contract": dict(self.robustness_matrix_contract),
            "walk_forward_contract": dict(self.walk_forward_contract),
        }

    @property
    def campaign_fingerprint(self) -> str:
        return fingerprint_identity(self.identity_payload())

    def to_record(self) -> dict[str, Any]:
        created = self.created_at
        if isinstance(created, datetime):
            created_meta = created.isoformat()
        else:
            created_meta = created
        return {
            "campaign_fingerprint": self.campaign_fingerprint,
            "created_at": created_meta,
            "identity": self.identity_payload(),
            "research_only": True,
            "total_return": False,
        }


__all__ = [
    "CAMPAIGN_VERSION",
    "EVALUATION_END_POLICY",
    "PRIMARY_COST_BPS_PER_SIDE",
    "PRIMARY_REBALANCE_SESSIONS",
    "PRIMARY_TARGET",
    "PRIMARY_TOP_PERCENT",
    "PRIMARY_WINDOW_START",
    "CanonicalEvidenceCampaignV1",
    "default_ablation_variants",
    "default_economic_primary_contract",
    "default_robustness_matrix_contract",
    "default_walk_forward_contract",
    "fingerprint_identity",
    "frozen_catboost_config_hash",
    "ranker_model_config_hash",
    "regression_model_config_hash",
    "SUPERSEDED_CAMPAIGN_FINGERPRINTS",
]
