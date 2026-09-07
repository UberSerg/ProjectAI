"""Shadow Portfolio V0 frozen experiment config."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG
from app.modules.simulator.config import (
    POLICY_HYSTERESIS_V1,
    RISK_DD_GUARD_V1,
    RISK_NAME,
    V1_DD_NORMAL_GROSS,
    V1_DD_RECOVERY,
    V1_DD_RISK_OFF_GROSS,
    V1_DD_TRIGGER,
    V1_ENTRY_QUANTILE,
    V1_EXIT_QUANTILE,
    V1_MIN_TRADE_WEIGHT_DELTA,
)

EXPERIMENT_GROUP = "SHADOW_FORWARD_V0"
SHADOW_KIND = "FORWARD_SHADOW"  # distinct from HISTORICAL_SIMULATOR

PORTFOLIO_A_NAME = "SHADOW_HYSTERESIS_V1"
PORTFOLIO_B_NAME = "SHADOW_HYSTERESIS_DD_V1"

# Lot-aware Realism V2 — same Prediction/Policy as operational V1; fresh capital; V1 frozen.
EXPERIMENT_GROUP_V2 = "SHADOW_PORTFOLIO_REALISM_V2"
PORTFOLIO_A_V2_NAME = "SHADOW_HYSTERESIS_V2"
PORTFOLIO_B_V2_NAME = "SHADOW_HYSTERESIS_DD_V2"
EXECUTION_VERSION_LOT_AWARE_V2 = "LOT_AWARE_V2"

# Prospective Model A/B V0 shadows. Same policy, same risk, same capital — only the
# Prediction Candidate differs, so any NAV gap is attributable to the model.
MODEL_AB_EXPERIMENT_GROUP = "PROSPECTIVE_MODEL_AB_V0"
MODEL_AB_PORTFOLIO_A_NAME = "MODEL_AB_V0_HYST"
MODEL_AB_PORTFOLIO_B_NAME = "MODEL_AB_V1_HYST"

INITIAL_CAPITAL = 1_000_000.0
EXPECTED_CANDIDATE_CONFIG_HASH = CANDIDATE_V0_CONFIG.config_hash()
EXPECTED_DATASET_VALUES_HASH = CANDIDATE_V0_CONFIG.required_values_hash


@dataclass(frozen=True, slots=True)
class ShadowSpecConfig:
    experiment_group: str
    name: str
    version: str
    candidate_name: str
    candidate_version: str
    candidate_config_hash: str
    dataset_values_hash: str
    policy_name: str
    risk_name: str
    entry_quantile: float = V1_ENTRY_QUANTILE
    exit_quantile: float = V1_EXIT_QUANTILE
    min_trade_weight_delta: float = V1_MIN_TRADE_WEIGHT_DELTA
    max_single_weight: float = 0.20
    dd_trigger: float | None = None
    dd_recovery: float | None = None
    dd_risk_off_gross: float | None = None
    dd_normal_gross: float | None = None
    initial_capital: float = INITIAL_CAPITAL
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    fractional_shares: bool = True
    dividend_cash: bool = False
    kind: str = SHADOW_KIND
    execution_version: str | None = None
    strategic_cash_reserve: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        payload = self.to_dict()
        if self.risk_name != RISK_DD_GUARD_V1:
            for key in ("dd_trigger", "dd_recovery", "dd_risk_off_gross", "dd_normal_gross"):
                payload.pop(key, None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def portfolio_a_config() -> ShadowSpecConfig:
    return ShadowSpecConfig(
        experiment_group=EXPERIMENT_GROUP,
        name=PORTFOLIO_A_NAME,
        version="v0",
        candidate_name=CANDIDATE_V0_CONFIG.candidate_name,
        candidate_version=CANDIDATE_V0_CONFIG.candidate_version,
        candidate_config_hash=EXPECTED_CANDIDATE_CONFIG_HASH,
        dataset_values_hash=EXPECTED_DATASET_VALUES_HASH,
        policy_name=POLICY_HYSTERESIS_V1,
        risk_name=RISK_NAME,
    )


def portfolio_b_config() -> ShadowSpecConfig:
    return ShadowSpecConfig(
        experiment_group=EXPERIMENT_GROUP,
        name=PORTFOLIO_B_NAME,
        version="v0",
        candidate_name=CANDIDATE_V0_CONFIG.candidate_name,
        candidate_version=CANDIDATE_V0_CONFIG.candidate_version,
        candidate_config_hash=EXPECTED_CANDIDATE_CONFIG_HASH,
        dataset_values_hash=EXPECTED_DATASET_VALUES_HASH,
        policy_name=POLICY_HYSTERESIS_V1,
        risk_name=RISK_DD_GUARD_V1,
        dd_trigger=V1_DD_TRIGGER,
        dd_recovery=V1_DD_RECOVERY,
        dd_risk_off_gross=V1_DD_RISK_OFF_GROSS,
        dd_normal_gross=V1_DD_NORMAL_GROSS,
    )


def operational_shadow_configs() -> tuple[ShadowSpecConfig, ShadowSpecConfig]:
    """The existing SHADOW_FORWARD_V0 operational pair."""
    return portfolio_a_config(), portfolio_b_config()


def model_ab_portfolio_a_config() -> ShadowSpecConfig:
    """Prospective A/B side A — Candidate V0 (EXPECTED_RETURN)."""
    return ShadowSpecConfig(
        experiment_group=MODEL_AB_EXPERIMENT_GROUP,
        name=MODEL_AB_PORTFOLIO_A_NAME,
        version="v0",
        candidate_name=CANDIDATE_V0_CONFIG.candidate_name,
        candidate_version=CANDIDATE_V0_CONFIG.candidate_version,
        candidate_config_hash=CANDIDATE_V0_CONFIG.config_hash(),
        dataset_values_hash=CANDIDATE_V0_CONFIG.required_values_hash,
        policy_name=POLICY_HYSTERESIS_V1,
        risk_name=RISK_NAME,
    )


def model_ab_portfolio_b_config() -> ShadowSpecConfig:
    """Prospective A/B side B — Candidate V1 Ranker (RANKING_SCORE)."""
    return ShadowSpecConfig(
        experiment_group=MODEL_AB_EXPERIMENT_GROUP,
        name=MODEL_AB_PORTFOLIO_B_NAME,
        version="v0",
        candidate_name=CANDIDATE_V1_RANKER_CONFIG.candidate_name,
        candidate_version=CANDIDATE_V1_RANKER_CONFIG.candidate_version,
        candidate_config_hash=CANDIDATE_V1_RANKER_CONFIG.config_hash(),
        dataset_values_hash=CANDIDATE_V1_RANKER_CONFIG.required_values_hash,
        policy_name=POLICY_HYSTERESIS_V1,
        risk_name=RISK_NAME,
    )


def model_ab_shadow_configs() -> tuple[ShadowSpecConfig, ShadowSpecConfig]:
    return model_ab_portfolio_a_config(), model_ab_portfolio_b_config()


def realism_v2_portfolio_a_config() -> ShadowSpecConfig:
    """Realism V2 A — same hysteresis policy as V1 A; integer lots only."""
    return ShadowSpecConfig(
        experiment_group=EXPERIMENT_GROUP_V2,
        name=PORTFOLIO_A_V2_NAME,
        version="v2",
        candidate_name=CANDIDATE_V0_CONFIG.candidate_name,
        candidate_version=CANDIDATE_V0_CONFIG.candidate_version,
        candidate_config_hash=EXPECTED_CANDIDATE_CONFIG_HASH,
        dataset_values_hash=EXPECTED_DATASET_VALUES_HASH,
        policy_name=POLICY_HYSTERESIS_V1,
        risk_name=RISK_NAME,
        fractional_shares=False,
        execution_version=EXECUTION_VERSION_LOT_AWARE_V2,
    )


def realism_v2_portfolio_b_config() -> ShadowSpecConfig:
    """Realism V2 B — same DD-guard policy as V1 B; integer lots only."""
    return ShadowSpecConfig(
        experiment_group=EXPERIMENT_GROUP_V2,
        name=PORTFOLIO_B_V2_NAME,
        version="v2",
        candidate_name=CANDIDATE_V0_CONFIG.candidate_name,
        candidate_version=CANDIDATE_V0_CONFIG.candidate_version,
        candidate_config_hash=EXPECTED_CANDIDATE_CONFIG_HASH,
        dataset_values_hash=EXPECTED_DATASET_VALUES_HASH,
        policy_name=POLICY_HYSTERESIS_V1,
        risk_name=RISK_DD_GUARD_V1,
        dd_trigger=V1_DD_TRIGGER,
        dd_recovery=V1_DD_RECOVERY,
        dd_risk_off_gross=V1_DD_RISK_OFF_GROSS,
        dd_normal_gross=V1_DD_NORMAL_GROSS,
        fractional_shares=False,
        execution_version=EXECUTION_VERSION_LOT_AWARE_V2,
    )


def realism_v2_shadow_configs() -> tuple[ShadowSpecConfig, ShadowSpecConfig]:
    return realism_v2_portfolio_a_config(), realism_v2_portfolio_b_config()


def operational_experiment_groups() -> tuple[str, ...]:
    """Groups advanced by the Daily Research Cycle Shadow stage."""
    return (EXPERIMENT_GROUP, EXPERIMENT_GROUP_V2)
