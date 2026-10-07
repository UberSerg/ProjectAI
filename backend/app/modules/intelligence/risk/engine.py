"""Risk + Scenario Engine V1 — produces RiskAssessmentV1.

Risk is not prediction. This module never emits crash probabilities or trade
orders. It does not mutate ``modules/risk`` product semantics.
"""

from __future__ import annotations

from app.modules.intelligence.contracts.risk import RiskAssessmentV1
from app.modules.intelligence.risk.constants import (
    ENGINE_ID,
    ENGINE_VERSION,
    LIMITATION_MISSING_INPUTS,
    LIMITATION_NO_CRASH_ODDS,
    LIMITATION_NOT_FORECAST,
    LIMITATION_PORTFOLIO_OPTIONAL,
)
from app.modules.intelligence.risk.inputs import RiskFactorInputs
from app.modules.intelligence.risk.scenarios import build_stress_scenarios
from app.modules.intelligence.risk.scoring import score_risk_factors


def assess_risk(inputs: RiskFactorInputs) -> RiskAssessmentV1:
    """Build a deterministic RiskAssessmentV1 from explicit factor inputs."""
    scored = score_risk_factors(inputs)
    scenarios = build_stress_scenarios(inputs)

    limitations: list[str] = [
        LIMITATION_NOT_FORECAST,
        LIMITATION_NO_CRASH_ODDS,
        LIMITATION_MISSING_INPUTS,
    ]
    if inputs.position_weight is None and inputs.position_nav is None:
        limitations.append(LIMITATION_PORTFOLIO_OPTIONAL)

    metadata = {
        "engine_id": ENGINE_ID,
        "engine_version": ENGINE_VERSION,
        "factor_scores": scored.factor_scores,
        "input_presence": {
            "realized_vol": inputs.realized_vol is not None,
            "atr_pct": inputs.atr_pct is not None,
            "drawdown": inputs.drawdown is not None,
            "avg_daily_value": inputs.avg_daily_value is not None,
            "spread_proxy_bps": inputs.spread_proxy_bps is not None,
            "market_regime": inputs.market_regime is not None,
            "event_risk_level": inputs.event_risk_level is not None,
            "ca_uncertainty": inputs.ca_uncertainty is not None,
            "fundamental_deterioration": inputs.fundamental_deterioration is not None,
            "stale_days": inputs.stale_days is not None,
            "position_weight": inputs.position_weight is not None,
            "position_nav": inputs.position_nav is not None,
        },
    }
    if inputs.metadata:
        metadata["caller"] = dict(inputs.metadata)

    return RiskAssessmentV1(
        as_of=inputs.as_of,
        instrument_id=int(inputs.instrument_id),
        risk_state=scored.risk_state,
        risk_score=scored.risk_score,
        risk_flags=scored.risk_flags,
        liquidity_state=scored.liquidity_state,
        volatility_state=scored.volatility_state,
        event_risk=scored.event_risk,
        data_risk=scored.data_risk,
        concentration_risk=scored.concentration_risk,
        scenarios=scenarios,
        limitations=tuple(limitations),
        evidence_refs=inputs.evidence_refs,
        metadata=metadata,
    )


class RiskScenarioEngine:
    """Thin callable wrapper for wiring / DI."""

    def assess(self, inputs: RiskFactorInputs) -> RiskAssessmentV1:
        return assess_risk(inputs)
