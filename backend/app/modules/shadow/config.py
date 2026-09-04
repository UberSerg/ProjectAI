"""Shadow Portfolio V0 frozen experiment config."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
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
