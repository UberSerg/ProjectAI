"""Risk budget V0 — deterministic constraints, not optimized."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RiskProfileId(StrEnum):
    CONSERVATIVE_ALLOCATION_V0 = "CONSERVATIVE_ALLOCATION_V0"
    BALANCED_ALLOCATION_V0 = "BALANCED_ALLOCATION_V0"
    GROWTH_ALLOCATION_V0 = "GROWTH_ALLOCATION_V0"


@dataclass(frozen=True, slots=True)
class RiskBudget:
    """Research configuration — values are not historically optimized."""

    profile_id: str
    max_equity_weight: float
    max_single_position: float
    max_credit_risk: str  # NONE | RESEARCH_UNKNOWN_OK | OBSERVED_ONLY
    min_cash: float
    max_fixed_income: float
    required_equity_premium: float
    max_volatility: float | None = None
    max_drawdown: float | None = None
    limitations: tuple[str, ...] = (
        "Deterministic research constraints — not an optimized risk engine",
    )


CONSERVATIVE_BUDGET = RiskBudget(
    profile_id=RiskProfileId.CONSERVATIVE_ALLOCATION_V0.value,
    max_equity_weight=0.30,
    max_single_position=0.10,
    max_credit_risk="NONE",
    min_cash=0.20,
    max_fixed_income=0.80,
    required_equity_premium=0.02,
)

BALANCED_BUDGET = RiskBudget(
    profile_id=RiskProfileId.BALANCED_ALLOCATION_V0.value,
    max_equity_weight=0.60,
    max_single_position=0.15,
    max_credit_risk="RESEARCH_UNKNOWN_OK",
    min_cash=0.10,
    max_fixed_income=0.70,
    required_equity_premium=0.0,
)

GROWTH_BUDGET = RiskBudget(
    profile_id=RiskProfileId.GROWTH_ALLOCATION_V0.value,
    max_equity_weight=0.90,
    max_single_position=0.20,
    max_credit_risk="RESEARCH_UNKNOWN_OK",
    min_cash=0.05,
    max_fixed_income=0.50,
    required_equity_premium=0.0,
)

RISK_BUDGETS: dict[str, RiskBudget] = {
    CONSERVATIVE_BUDGET.profile_id: CONSERVATIVE_BUDGET,
    BALANCED_BUDGET.profile_id: BALANCED_BUDGET,
    GROWTH_BUDGET.profile_id: GROWTH_BUDGET,
}


def get_risk_budget(profile_id: str) -> RiskBudget:
    try:
        return RISK_BUDGETS[profile_id]
    except KeyError as exc:
        raise KeyError(f"Unknown risk profile: {profile_id}") from exc
