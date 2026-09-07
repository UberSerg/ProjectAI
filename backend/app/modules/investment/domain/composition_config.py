"""Typed operational limits for Concrete Portfolio Composition V1.

Not optimized on historical returns — documented research defaults for ~100k RUB.
"""

from __future__ import annotations

from dataclasses import dataclass

EQUITY_COMPOSITION_VERSION = "EQUITY_COMPOSITION_V1"
FIXED_INCOME_COMPOSITION_VERSION = "FIXED_INCOME_COMPOSITION_V1"
CONCRETE_CANDIDATE_VERSION = "CONCRETE_PORTFOLIO_CANDIDATE_V1"


@dataclass(frozen=True, slots=True)
class CompositionConfig:
    """Deterministic selection / sizing knobs for research composition."""

    max_equity_positions: int = 4
    max_fixed_income_positions: int = 5  # allows ~70% FI sleeve under 15% concentration cap
    min_position_rub: float = 3_000.0
    max_single_position_weight: float = 0.15
    # Equity LOTSIZE must come from MOEX source_metadata / ISS — never invent default=1.
    prefer_government_bonds: bool = True
    cost_bps: float = 5.0
    stale_after_days: int = 10
    max_rejected_shown: int = 12

    equity_policy_version: str = EQUITY_COMPOSITION_VERSION
    fixed_income_policy_version: str = FIXED_INCOME_COMPOSITION_VERSION
    candidate_version: str = CONCRETE_CANDIDATE_VERSION


DEFAULT_COMPOSITION_CONFIG = CompositionConfig()
