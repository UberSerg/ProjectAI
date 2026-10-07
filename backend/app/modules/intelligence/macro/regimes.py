"""Deterministic first-pass regime classification (predeclared thresholds)."""

from __future__ import annotations

from typing import Any

from app.modules.intelligence.macro.constants import (
    FX_STABLE,
    FX_STRENGTHEN_MAX,
    FX_STRENGTHENING,
    FX_UNKNOWN,
    FX_WEAKEN_MIN,
    FX_WEAKENING,
    RATE_EASE_PP,
    RATE_EASING,
    RATE_NEUTRAL,
    RATE_TIGHTEN_PP,
    RATE_TIGHTENING,
    RATE_UNKNOWN,
    REGIME_FX,
    REGIME_MARKET_TREND,
    REGIME_RATE,
    REGIME_VOLATILITY,
    TREND_NEUTRAL,
    TREND_RISK_OFF,
    TREND_RISK_OFF_MAX,
    TREND_RISK_ON,
    TREND_RISK_ON_MIN,
    TREND_UNKNOWN,
    VOL_CALM,
    VOL_CALM_MAX,
    VOL_ELEVATED,
    VOL_STRESS,
    VOL_STRESS_MIN,
    VOL_UNKNOWN,
)


def classify_rate(key_rate_change_pp: float | None) -> str:
    if key_rate_change_pp is None:
        return RATE_UNKNOWN
    if key_rate_change_pp <= RATE_EASE_PP:
        return RATE_EASING
    if key_rate_change_pp >= RATE_TIGHTEN_PP:
        return RATE_TIGHTENING
    return RATE_NEUTRAL


def classify_market_trend(imoex_return_20d: float | None) -> str:
    if imoex_return_20d is None:
        return TREND_UNKNOWN
    if imoex_return_20d >= TREND_RISK_ON_MIN:
        return TREND_RISK_ON
    if imoex_return_20d <= TREND_RISK_OFF_MAX:
        return TREND_RISK_OFF
    return TREND_NEUTRAL


def classify_volatility(realized_vol_20d: float | None) -> str:
    if realized_vol_20d is None:
        return VOL_UNKNOWN
    if realized_vol_20d < VOL_CALM_MAX:
        return VOL_CALM
    if realized_vol_20d > VOL_STRESS_MIN:
        return VOL_STRESS
    return VOL_ELEVATED


def classify_fx(usd_rub_pct_change_20d: float | None) -> str:
    """Positive USD/RUB change ⇒ RUB weakening."""
    if usd_rub_pct_change_20d is None:
        return FX_UNKNOWN
    if usd_rub_pct_change_20d <= FX_STRENGTHEN_MAX:
        return FX_STRENGTHENING
    if usd_rub_pct_change_20d >= FX_WEAKEN_MIN:
        return FX_WEAKENING
    return FX_STABLE


def classify_regimes(observations: dict[str, Any]) -> dict[str, str]:
    """Map observation dict → regime labels. Never peeks at future returns."""
    rate_chg = _nested_num(observations, "key_rate_change_pp", "value")
    imoex_ret = _nested_num(observations, "imoex_return_20d", "value")
    imoex_vol = _nested_num(observations, "imoex_realized_vol_20d", "value")
    fx_chg = _nested_num(observations, "usd_rub_pct_change_20d", "value")
    return {
        REGIME_RATE: classify_rate(rate_chg),
        REGIME_MARKET_TREND: classify_market_trend(imoex_ret),
        REGIME_VOLATILITY: classify_volatility(imoex_vol),
        REGIME_FX: classify_fx(fx_chg),
    }


def _nested_num(obs: dict[str, Any], key: str, field: str = "value") -> float | None:
    raw = obs.get(key)
    if raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, dict):
        val = raw.get(field)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    return None
