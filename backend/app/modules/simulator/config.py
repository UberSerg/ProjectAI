"""Frozen Historical Simulator configuration (V0 + Policy/Risk V1 research knobs)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

SimulationSegment = Literal["DEVELOPMENT_OOS", "FINAL_HOLDOUT"]

POLICY_NAME = "RANK_LONG_ONLY_V0"
POLICY_HYSTERESIS_V1 = "RANK_HYSTERESIS_LONG_ONLY_V1"
RISK_NAME = "RISK_GUARDRAILS_V0"
RISK_DD_GUARD_V1 = "DRAWDOWN_GUARD_V1"
EXECUTION_NAME = "HISTORICAL_NEXT_OPEN_V0"

CANONICAL_INITIAL_CAPITAL = 1_000_000.0
CANONICAL_TOP_QUANTILE = 0.20
CANONICAL_MAX_SINGLE_WEIGHT = 0.20
CANONICAL_REBALANCE = "weekly_first_trading_day"
CANONICAL_EXECUTION = "next_open"

# Policy V1 research defaults (predeclared — do not tune on 2026 holdout)
V1_ENTRY_QUANTILE = 0.20
V1_EXIT_QUANTILE = 0.35
V1_MIN_TRADE_WEIGHT_DELTA = 0.02  # 2 percentage points

# Drawdown guard V1 research defaults
V1_DD_TRIGGER = -0.20
V1_DD_RECOVERY = -0.10
V1_DD_RISK_OFF_GROSS = 0.50
V1_DD_NORMAL_GROSS = 1.00


@dataclass(frozen=True, slots=True)
class SimulationSpecV0:
    """Immutable simulation identity — freeze policy before holdout research."""

    segment: SimulationSegment
    candidate_name: str = "prediction_ml_candidate"
    candidate_version: str = "v0"
    candidate_config_hash: str = ""
    dataset_values_hash: str = ""
    prediction_hash: str = ""
    policy_name: str = POLICY_NAME
    top_quantile: float = CANONICAL_TOP_QUANTILE
    rebalance: str = CANONICAL_REBALANCE
    execution_timing: str = CANONICAL_EXECUTION
    initial_capital: float = CANONICAL_INITIAL_CAPITAL
    currency: str = "RUB"
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    fractional_shares: bool = True
    dividend_cash: bool = False
    max_single_weight: float = CANONICAL_MAX_SINGLE_WEIGHT
    max_gross_exposure: float = 1.0
    long_only: bool = True
    cash_return: float = 0.0
    risk_name: str = RISK_NAME
    execution_name: str = EXECUTION_NAME
    cost_sensitivity_label: str | None = None
    # Policy V1 knobs (inactive for RANK_LONG_ONLY_V0)
    entry_quantile: float = V1_ENTRY_QUANTILE
    exit_quantile: float = V1_EXIT_QUANTILE
    min_trade_weight_delta: float = 0.0
    # Drawdown guard V1 knobs (inactive for RISK_GUARDRAILS_V0)
    dd_trigger: float = V1_DD_TRIGGER
    dd_recovery: float = V1_DD_RECOVERY
    dd_risk_off_gross: float = V1_DD_RISK_OFF_GROSS
    dd_normal_gross: float = V1_DD_NORMAL_GROSS
    survivorship_disclaimer: str = (
        "Current supported cohort only; survivorship bias present; "
        "not whole-market historical investability. Dividends excluded / unavailable."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        payload = {k: v for k, v in self.to_dict().items() if k != "cost_sensitivity_label"}
        # Preserve V0 hash identity when V1 knobs are unused.
        if self.policy_name == POLICY_NAME:
            for key in ("entry_quantile", "exit_quantile", "min_trade_weight_delta"):
                payload.pop(key, None)
        if self.risk_name == RISK_NAME:
            for key in ("dd_trigger", "dd_recovery", "dd_risk_off_gross", "dd_normal_gross"):
                payload.pop(key, None)
        if self.cost_sensitivity_label:
            payload["cost_sensitivity_label"] = self.cost_sensitivity_label
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def hysteresis_v1_spec_kwargs() -> dict[str, Any]:
    return {
        "policy_name": POLICY_HYSTERESIS_V1,
        "top_quantile": V1_ENTRY_QUANTILE,
        "entry_quantile": V1_ENTRY_QUANTILE,
        "exit_quantile": V1_EXIT_QUANTILE,
        "min_trade_weight_delta": V1_MIN_TRADE_WEIGHT_DELTA,
        "risk_name": RISK_NAME,
    }


def hysteresis_dd_v1_spec_kwargs() -> dict[str, Any]:
    return {
        **hysteresis_v1_spec_kwargs(),
        "risk_name": RISK_DD_GUARD_V1,
        "dd_trigger": V1_DD_TRIGGER,
        "dd_recovery": V1_DD_RECOVERY,
        "dd_risk_off_gross": V1_DD_RISK_OFF_GROSS,
        "dd_normal_gross": V1_DD_NORMAL_GROSS,
    }
