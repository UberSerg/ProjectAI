"""Deterministic factor scoring → risk_state / sub-states / flags.

Missing inputs raise data_risk / UNKNOWN sub-states — they do not score as safe.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.intelligence.contracts.risk import RiskState
from app.modules.intelligence.risk.constants import (
    ADV_HIGH_MIN,
    ADV_LOW_MIN,
    ADV_MODERATE_MIN,
    ATR_ELEVATED_MAX,
    ATR_LOW_MAX,
    ATR_MODERATE_MAX,
    CONCENTRATION_HIGH,
    CONCENTRATION_WARN,
    DD_ELEVATED_MAX,
    DD_LOW_MAX,
    DD_MODERATE_MAX,
    REGIME_HIGH_VOL,
    REGIME_NEUTRAL,
    REGIME_RISK_OFF,
    REGIME_RISK_ON,
    REGIME_STRESS,
    REGIME_UNKNOWN,
    SEVERITY_ELEVATED,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MODERATE,
    SEVERITY_NONE,
    SEVERITY_UNKNOWN,
    SPREAD_ELEVATED_MAX_BPS,
    SPREAD_LOW_MAX_BPS,
    SPREAD_MODERATE_MAX_BPS,
    STALE_DAYS_HIGH,
    STALE_DAYS_WARN,
    STATE_ELEVATED_MAX,
    STATE_LOW_MAX,
    STATE_MODERATE_MAX,
    VOL_ELEVATED_MAX,
    VOL_LOW_MAX,
    VOL_MODERATE_MAX,
    WEIGHT_CA,
    WEIGHT_DATA,
    WEIGHT_DRAWDOWN,
    WEIGHT_EVENT,
    WEIGHT_FUNDAMENTAL,
    WEIGHT_LIQUIDITY,
    WEIGHT_REGIME,
    WEIGHT_VOLATILITY,
)
from app.modules.intelligence.risk.inputs import RiskFactorInputs

_SEVERITY_SCORE: dict[str, float] = {
    SEVERITY_NONE: 0.0,
    SEVERITY_LOW: 0.15,
    SEVERITY_MODERATE: 0.40,
    SEVERITY_ELEVATED: 0.70,
    SEVERITY_HIGH: 1.0,
    SEVERITY_UNKNOWN: 0.55,
}

_LEVEL_ALIASES: dict[str, str] = {
    "NONE": SEVERITY_NONE,
    "LOW": SEVERITY_LOW,
    "MODERATE": SEVERITY_MODERATE,
    "MEDIUM": SEVERITY_MODERATE,
    "ELEVATED": SEVERITY_ELEVATED,
    "HIGH": SEVERITY_HIGH,
    "SEVERE": SEVERITY_HIGH,
    "CRITICAL": SEVERITY_HIGH,
    "UNKNOWN": SEVERITY_UNKNOWN,
    "PENDING": SEVERITY_ELEVATED,
    "MILD": SEVERITY_MODERATE,
}


@dataclass(frozen=True, slots=True)
class ScoredRiskFactors:
    risk_score: float
    risk_state: RiskState
    risk_flags: tuple[str, ...]
    liquidity_state: str
    volatility_state: str
    event_risk: str
    data_risk: str
    concentration_risk: str
    factor_scores: dict[str, float]


def _normalize_level(raw: str | None, *, default: str = SEVERITY_UNKNOWN) -> str:
    if raw is None or not str(raw).strip():
        return default
    key = str(raw).strip().upper()
    return _LEVEL_ALIASES.get(key, SEVERITY_UNKNOWN)


def _band_from_thresholds(
    value: float | None,
    *,
    low_max: float,
    moderate_max: float,
    elevated_max: float,
) -> str:
    if value is None:
        return SEVERITY_UNKNOWN
    v = float(value)
    if v <= low_max:
        return SEVERITY_LOW
    if v <= moderate_max:
        return SEVERITY_MODERATE
    if v <= elevated_max:
        return SEVERITY_ELEVATED
    return SEVERITY_HIGH


def _worse(a: str, b: str) -> str:
    order = (
        SEVERITY_NONE,
        SEVERITY_LOW,
        SEVERITY_MODERATE,
        SEVERITY_UNKNOWN,
        SEVERITY_ELEVATED,
        SEVERITY_HIGH,
    )
    return a if order.index(a) >= order.index(b) else b


def _score_volatility(inputs: RiskFactorInputs) -> tuple[str, float, tuple[str, ...]]:
    flags: list[str] = []
    vol_band = _band_from_thresholds(
        inputs.realized_vol,
        low_max=VOL_LOW_MAX,
        moderate_max=VOL_MODERATE_MAX,
        elevated_max=VOL_ELEVATED_MAX,
    )
    atr_band = _band_from_thresholds(
        inputs.atr_pct,
        low_max=ATR_LOW_MAX,
        moderate_max=ATR_MODERATE_MAX,
        elevated_max=ATR_ELEVATED_MAX,
    )
    if inputs.realized_vol is None and inputs.atr_pct is None:
        state = SEVERITY_UNKNOWN
        flags.append("volatility_missing")
    else:
        state = _worse(vol_band, atr_band)
        if state in (SEVERITY_ELEVATED, SEVERITY_HIGH):
            flags.append("elevated_volatility")
    return state, _SEVERITY_SCORE[state], tuple(flags)


def _score_drawdown(inputs: RiskFactorInputs) -> tuple[str, float, tuple[str, ...]]:
    mag = inputs.drawdown_magnitude()
    state = _band_from_thresholds(
        mag,
        low_max=DD_LOW_MAX,
        moderate_max=DD_MODERATE_MAX,
        elevated_max=DD_ELEVATED_MAX,
    )
    flags: list[str] = []
    if mag is None:
        flags.append("drawdown_missing")
    elif state in (SEVERITY_ELEVATED, SEVERITY_HIGH):
        flags.append("deep_drawdown")
    return state, _SEVERITY_SCORE[state], tuple(flags)


def _score_liquidity(inputs: RiskFactorInputs) -> tuple[str, float, tuple[str, ...]]:
    flags: list[str] = []
    if inputs.liquidity_state_hint:
        state = _normalize_level(inputs.liquidity_state_hint)
    else:
        adv_state = SEVERITY_UNKNOWN
        if inputs.avg_daily_value is not None:
            adv = float(inputs.avg_daily_value)
            if adv >= ADV_HIGH_MIN:
                adv_state = SEVERITY_LOW
            elif adv >= ADV_MODERATE_MIN:
                adv_state = SEVERITY_MODERATE
            elif adv >= ADV_LOW_MIN:
                adv_state = SEVERITY_ELEVATED
            else:
                adv_state = SEVERITY_HIGH
        spread_state = _band_from_thresholds(
            inputs.spread_proxy_bps,
            low_max=SPREAD_LOW_MAX_BPS,
            moderate_max=SPREAD_MODERATE_MAX_BPS,
            elevated_max=SPREAD_ELEVATED_MAX_BPS,
        )
        if inputs.avg_daily_value is None and inputs.spread_proxy_bps is None:
            state = SEVERITY_UNKNOWN
            flags.append("liquidity_missing")
        else:
            state = _worse(adv_state, spread_state)
    if state in (SEVERITY_ELEVATED, SEVERITY_HIGH):
        flags.append("thin_liquidity")
    return state, _SEVERITY_SCORE[state], tuple(flags)


def _score_regime(inputs: RiskFactorInputs) -> tuple[str, float, tuple[str, ...]]:
    flags: list[str] = []
    raw = (inputs.market_regime or "").strip().upper() or REGIME_UNKNOWN
    mapping = {
        REGIME_RISK_ON: SEVERITY_LOW,
        REGIME_NEUTRAL: SEVERITY_LOW,
        REGIME_HIGH_VOL: SEVERITY_ELEVATED,
        REGIME_RISK_OFF: SEVERITY_ELEVATED,
        REGIME_STRESS: SEVERITY_HIGH,
        REGIME_UNKNOWN: SEVERITY_UNKNOWN,
    }
    state = mapping.get(raw, SEVERITY_UNKNOWN)
    if state == SEVERITY_UNKNOWN and raw == REGIME_UNKNOWN:
        flags.append("regime_unknown")
    elif state in (SEVERITY_ELEVATED, SEVERITY_HIGH):
        flags.append("adverse_regime")
    return state, _SEVERITY_SCORE[state], tuple(flags)


def _score_event(inputs: RiskFactorInputs) -> tuple[str, float, tuple[str, ...]]:
    flags: list[str] = []
    state = _normalize_level(inputs.event_risk_level, default=SEVERITY_NONE)
    if inputs.event_risk_level is None and not inputs.material_adverse_event:
        # Explicit absence of event feed ≠ "no events"; treat as unknown mild.
        state = SEVERITY_UNKNOWN
        flags.append("event_risk_unobserved")
    if inputs.material_adverse_event:
        state = SEVERITY_HIGH
        flags.append("material_adverse_event")
    elif state in (SEVERITY_ELEVATED, SEVERITY_HIGH):
        flags.append("elevated_event_risk")
    return state, _SEVERITY_SCORE[state], tuple(flags)


def _score_ca(inputs: RiskFactorInputs) -> tuple[str, float, tuple[str, ...]]:
    flags: list[str] = []
    if inputs.ca_uncertainty is None:
        state = SEVERITY_UNKNOWN
        flags.append("ca_uncertainty_unobserved")
    else:
        state = _normalize_level(inputs.ca_uncertainty, default=SEVERITY_UNKNOWN)
        if state in (SEVERITY_ELEVATED, SEVERITY_HIGH):
            flags.append("corporate_action_uncertainty")
    return state, _SEVERITY_SCORE[state], tuple(flags)


def _score_fundamental(inputs: RiskFactorInputs) -> tuple[str, float, tuple[str, ...]]:
    flags: list[str] = []
    if inputs.fundamental_deterioration is None:
        state = SEVERITY_UNKNOWN
        flags.append("fundamental_deterioration_unobserved")
    else:
        state = _normalize_level(inputs.fundamental_deterioration, default=SEVERITY_UNKNOWN)
        if state in (SEVERITY_ELEVATED, SEVERITY_HIGH):
            flags.append("fundamental_deterioration")
    return state, _SEVERITY_SCORE[state], tuple(flags)


def _score_data(inputs: RiskFactorInputs) -> tuple[str, float, tuple[str, ...]]:
    flags: list[str] = []
    state = SEVERITY_LOW
    if inputs.data_missing_critical:
        state = SEVERITY_HIGH
        flags.append("critical_data_missing")
    stale_days = inputs.stale_days
    if inputs.data_stale or (stale_days is not None and stale_days >= STALE_DAYS_WARN):
        if stale_days is not None and stale_days >= STALE_DAYS_HIGH:
            state = _worse(state, SEVERITY_HIGH)
            flags.append("severely_stale_data")
        else:
            state = _worse(state, SEVERITY_ELEVATED)
            flags.append("stale_data")
    if state == SEVERITY_LOW and stale_days is None and not inputs.data_stale:
        # No freshness signal provided.
        state = SEVERITY_UNKNOWN
        flags.append("data_freshness_unobserved")
    return state, _SEVERITY_SCORE[state], tuple(flags)


def _score_concentration(inputs: RiskFactorInputs) -> tuple[str, float, tuple[str, ...]]:
    flags: list[str] = []
    weight = inputs.position_weight
    if weight is None:
        return SEVERITY_UNKNOWN, _SEVERITY_SCORE[SEVERITY_UNKNOWN], ("concentration_context_absent",)
    w = float(weight)
    if w >= CONCENTRATION_HIGH:
        state = SEVERITY_HIGH
        flags.append("high_concentration")
    elif w >= CONCENTRATION_WARN:
        state = SEVERITY_ELEVATED
        flags.append("concentration_warning")
    else:
        state = SEVERITY_LOW
    return state, _SEVERITY_SCORE[state], tuple(flags)


def score_to_risk_state(score: float, *, force_unknown: bool = False) -> RiskState:
    if force_unknown:
        return "UNKNOWN"
    s = float(score)
    if s <= STATE_LOW_MAX:
        return "LOW"
    if s <= STATE_MODERATE_MAX:
        return "MODERATE"
    if s <= STATE_ELEVATED_MAX:
        return "ELEVATED"
    return "HIGH"


def score_risk_factors(inputs: RiskFactorInputs) -> ScoredRiskFactors:
    vol_state, vol_score, vol_flags = _score_volatility(inputs)
    dd_state, dd_score, dd_flags = _score_drawdown(inputs)
    liq_state, liq_score, liq_flags = _score_liquidity(inputs)
    _regime_state, regime_score, regime_flags = _score_regime(inputs)
    event_state, event_score, event_flags = _score_event(inputs)
    _ca_state, ca_score, ca_flags = _score_ca(inputs)
    _fund_state, fund_score, fund_flags = _score_fundamental(inputs)
    data_state, data_score, data_flags = _score_data(inputs)
    conc_state, conc_score, conc_flags = _score_concentration(inputs)

    # Concentration informs flags always; enters the score only with portfolio context.
    weighted = (
        WEIGHT_VOLATILITY * vol_score
        + WEIGHT_DRAWDOWN * dd_score
        + WEIGHT_LIQUIDITY * liq_score
        + WEIGHT_REGIME * regime_score
        + WEIGHT_EVENT * event_score
        + WEIGHT_CA * ca_score
        + WEIGHT_FUNDAMENTAL * fund_score
        + WEIGHT_DATA * data_score
    )
    weight_sum = (
        WEIGHT_VOLATILITY
        + WEIGHT_DRAWDOWN
        + WEIGHT_LIQUIDITY
        + WEIGHT_REGIME
        + WEIGHT_EVENT
        + WEIGHT_CA
        + WEIGHT_FUNDAMENTAL
        + WEIGHT_DATA
    )
    core = weighted / weight_sum
    if inputs.position_weight is not None:
        risk_score = max(0.0, min(1.0, 0.90 * core + 0.10 * conc_score))
    else:
        risk_score = max(0.0, min(1.0, core))

    flags = (
        vol_flags
        + dd_flags
        + liq_flags
        + regime_flags
        + event_flags
        + ca_flags
        + fund_flags
        + data_flags
        + conc_flags
    )

    force_unknown = inputs.data_missing_critical and (
        inputs.realized_vol is None and inputs.atr_pct is None and inputs.drawdown is None
    )
    if inputs.material_adverse_event:
        risk_score = max(risk_score, 0.85)
    risk_state = score_to_risk_state(risk_score, force_unknown=force_unknown)
    if inputs.material_adverse_event and risk_state not in ("HIGH", "UNKNOWN"):
        risk_state = "HIGH"

    return ScoredRiskFactors(
        risk_score=round(risk_score, 6),
        risk_state=risk_state,
        risk_flags=tuple(dict.fromkeys(flags)),
        liquidity_state=liq_state,
        volatility_state=vol_state,
        event_risk=event_state,
        data_risk=data_state,
        concentration_risk=conc_state,
        factor_scores={
            "volatility": vol_score,
            "drawdown": dd_score,
            "liquidity": liq_score,
            "regime": regime_score,
            "event": event_score,
            "ca_uncertainty": ca_score,
            "fundamental": fund_score,
            "data": data_score,
            "concentration": conc_score,
        },
    )
