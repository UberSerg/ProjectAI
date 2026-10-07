"""Deterministic stress scenarios — not probabilistic crash forecasts."""

from __future__ import annotations

from app.modules.intelligence.contracts.risk import ScenarioImpact
from app.modules.intelligence.risk.constants import (
    COST_BASELINE_BPS,
    COST_STRESSED_BPS,
    PRICE_SHOCK_M10,
    PRICE_SHOCK_M20,
    SCENARIO_COST_WIDEN,
    SCENARIO_PRICE_M10,
    SCENARIO_PRICE_M20,
    SCENARIO_SECTOR_DD,
    SCENARIO_VOL_SHOCK,
    SECTOR_DRAWDOWN_SHOCK,
    VOL_SHOCK_MULTIPLIER,
)
from app.modules.intelligence.risk.inputs import RiskFactorInputs


def _nav_impact(price_shock: float, position_nav: float | None) -> float | None:
    if position_nav is None:
        return price_shock
    return float(position_nav) * float(price_shock)


def build_stress_scenarios(inputs: RiskFactorInputs) -> tuple[ScenarioImpact, ...]:
    """Fixed scenario set. Scenario ≠ forecast; no crash-probability claims."""

    nav = inputs.position_nav
    atr = inputs.atr_pct
    vol = inputs.realized_vol

    vol_notes: list[str] = [
        f"ATR/vol multiplied by {VOL_SHOCK_MULTIPLIER:g} for stress sizing checks",
        "not a probability of a volatility spike",
    ]
    if atr is not None:
        vol_notes.append(f"baseline_atr_pct={float(atr):.6f}")
        vol_notes.append(f"stressed_atr_pct={float(atr) * VOL_SHOCK_MULTIPLIER:.6f}")
    if vol is not None:
        vol_notes.append(f"baseline_realized_vol={float(vol):.6f}")
        vol_notes.append(f"stressed_realized_vol={float(vol) * VOL_SHOCK_MULTIPLIER:.6f}")

    cost_delta_frac = (COST_STRESSED_BPS - COST_BASELINE_BPS) / 10_000.0
    cost_nav = (-abs(float(nav)) * cost_delta_frac) if nav is not None else -cost_delta_frac

    return (
        ScenarioImpact(
            scenario_id=SCENARIO_PRICE_M10,
            description="Instantaneous price shock of -10% (deterministic stress)",
            price_shock=PRICE_SHOCK_M10,
            nav_impact=_nav_impact(PRICE_SHOCK_M10, nav),
            notes=("scenario_not_forecast", "no_crash_probability"),
        ),
        ScenarioImpact(
            scenario_id=SCENARIO_PRICE_M20,
            description="Instantaneous price shock of -20% (deterministic stress)",
            price_shock=PRICE_SHOCK_M20,
            nav_impact=_nav_impact(PRICE_SHOCK_M20, nav),
            notes=("scenario_not_forecast", "no_crash_probability"),
        ),
        ScenarioImpact(
            scenario_id=SCENARIO_VOL_SHOCK,
            description=(
                f"Volatility shock: scale ATR/realized vol by {VOL_SHOCK_MULTIPLIER:g}x"
            ),
            price_shock=None,
            nav_impact=None,
            notes=tuple(vol_notes),
        ),
        ScenarioImpact(
            scenario_id=SCENARIO_COST_WIDEN,
            description=(
                f"Transaction cost widening from {COST_BASELINE_BPS:g} to "
                f"{COST_STRESSED_BPS:g} bps round-trip"
            ),
            price_shock=None,
            nav_impact=cost_nav,
            notes=(
                "cost_impact_on_round_trip_notional",
                "scenario_not_forecast",
            ),
        ),
        ScenarioImpact(
            scenario_id=SCENARIO_SECTOR_DD,
            description="Sector drawdown stress of -15% applied to position",
            price_shock=SECTOR_DRAWDOWN_SHOCK,
            nav_impact=_nav_impact(SECTOR_DRAWDOWN_SHOCK, nav),
            notes=("sector_proxy_shock", "scenario_not_forecast"),
        ),
    )
