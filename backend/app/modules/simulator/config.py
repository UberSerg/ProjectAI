"""Frozen Historical Simulator V0 configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

SimulationSegment = Literal["DEVELOPMENT_OOS", "FINAL_HOLDOUT"]

POLICY_NAME = "RANK_LONG_ONLY_V0"
RISK_NAME = "RISK_GUARDRAILS_V0"
EXECUTION_NAME = "HISTORICAL_NEXT_OPEN_V0"

CANONICAL_INITIAL_CAPITAL = 1_000_000.0
CANONICAL_TOP_QUANTILE = 0.20
CANONICAL_MAX_SINGLE_WEIGHT = 0.20
CANONICAL_REBALANCE = "weekly_first_trading_day"
CANONICAL_EXECUTION = "next_open"


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
    survivorship_disclaimer: str = (
        "Current supported cohort only; survivorship bias present; "
        "not whole-market historical investability. Dividends excluded / unavailable."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        payload = {k: v for k, v in self.to_dict().items() if k != "cost_sensitivity_label"}
        # Include cost label in hash when sensitivity run is named, else keep canonical hash
        # stable for zero-cost primary.
        if self.cost_sensitivity_label:
            payload["cost_sensitivity_label"] = self.cost_sensitivity_label
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
