"""Predeclared Risk Engine V1 vocabulary and thresholds.

Risk ≠ prediction. Thresholds are research defaults — not tuned to historical
outcomes after seeing results.
"""

from __future__ import annotations

ENGINE_ID = "RiskScenarioEngineV1"
ENGINE_VERSION = "1"

LIMITATION_NOT_FORECAST = "scenario_not_forecast"
LIMITATION_NO_CRASH_ODDS = "no_probabilistic_crash_odds"
LIMITATION_MISSING_INPUTS = "missing_risk_inputs_treated_as_unknown_not_zero"
LIMITATION_PORTFOLIO_OPTIONAL = "concentration_and_nav_impact_require_portfolio_context"

# Severity labels used on sub-states (liquidity / volatility / event / data / concentration).
SEVERITY_UNKNOWN = "UNKNOWN"
SEVERITY_LOW = "LOW"
SEVERITY_MODERATE = "MODERATE"
SEVERITY_ELEVATED = "ELEVATED"
SEVERITY_HIGH = "HIGH"
SEVERITY_NONE = "NONE"

# Realized vol (annualized fraction) bands.
VOL_LOW_MAX = 0.18
VOL_MODERATE_MAX = 0.30
VOL_ELEVATED_MAX = 0.45

# ATR% of price bands (daily).
ATR_LOW_MAX = 0.015
ATR_MODERATE_MAX = 0.030
ATR_ELEVATED_MAX = 0.050

# Drawdown magnitude (positive fraction, e.g. 0.12 = 12% off peak).
DD_LOW_MAX = 0.05
DD_MODERATE_MAX = 0.12
DD_ELEVATED_MAX = 0.20

# Liquidity: average daily traded value (RUB) and spread proxy (bps).
ADV_HIGH_MIN = 50_000_000.0
ADV_MODERATE_MIN = 5_000_000.0
ADV_LOW_MIN = 500_000.0
SPREAD_LOW_MAX_BPS = 20.0
SPREAD_MODERATE_MAX_BPS = 80.0
SPREAD_ELEVATED_MAX_BPS = 200.0

# Concentration (portfolio weight fraction).
CONCENTRATION_WARN = 0.12
CONCENTRATION_HIGH = 0.15

# Stale data.
STALE_DAYS_WARN = 5
STALE_DAYS_HIGH = 20

# Factor score contributions in [0, 1] before clamp of aggregate.
WEIGHT_VOLATILITY = 0.20
WEIGHT_DRAWDOWN = 0.18
WEIGHT_LIQUIDITY = 0.14
WEIGHT_REGIME = 0.10
WEIGHT_EVENT = 0.14
WEIGHT_CA = 0.08
WEIGHT_FUNDAMENTAL = 0.10
WEIGHT_DATA = 0.06

# Aggregate score → risk_state.
STATE_LOW_MAX = 0.25
STATE_MODERATE_MAX = 0.45
STATE_ELEVATED_MAX = 0.70

# Deterministic stress scenario ids.
SCENARIO_PRICE_M10 = "price_shock_m10"
SCENARIO_PRICE_M20 = "price_shock_m20"
SCENARIO_VOL_SHOCK = "volatility_shock"
SCENARIO_COST_WIDEN = "transaction_cost_widening"
SCENARIO_SECTOR_DD = "sector_drawdown"

PRICE_SHOCK_M10 = -0.10
PRICE_SHOCK_M20 = -0.20
SECTOR_DRAWDOWN_SHOCK = -0.15
VOL_SHOCK_MULTIPLIER = 2.0
# Round-trip cost widening: baseline 20 bps → stressed 80 bps (fraction of notional).
COST_BASELINE_BPS = 20.0
COST_STRESSED_BPS = 80.0

REGIME_RISK_OFF = "RISK_OFF"
REGIME_HIGH_VOL = "HIGH_VOL"
REGIME_STRESS = "STRESS"
REGIME_RISK_ON = "RISK_ON"
REGIME_NEUTRAL = "NEUTRAL"
REGIME_UNKNOWN = "UNKNOWN"
