"""Predeclared macro regime thresholds — no look-ahead calibration."""

from app.modules.intelligence.macro.regimes import (
    classify_fx,
    classify_market_trend,
    classify_rate,
    classify_regimes,
    classify_volatility,
)


def test_rate_and_trend_thresholds() -> None:
    assert classify_rate(-0.5) == "easing"
    assert classify_rate(0.5) == "tightening"
    assert classify_rate(0.0) == "neutral"
    assert classify_rate(None) == "unknown"
    assert classify_market_trend(0.05) == "risk-on"
    assert classify_market_trend(-0.05) == "risk-off"
    assert classify_volatility(0.004) == "calm"
    assert classify_volatility(0.02) == "stress"
    assert classify_fx(-0.03) == "strengthening"
    assert classify_fx(0.03) == "weakening"


def test_classify_regimes_from_nested_observations() -> None:
    regimes = classify_regimes(
        {
            "key_rate_change_pp": {"value": 0.0},
            "imoex_return_20d": {"value": 0.01},
            "imoex_realized_vol_20d": {"value": 0.01},
            "usd_rub_pct_change_20d": {"value": 0.0},
        }
    )
    assert regimes["RATE"] == "neutral"
    assert regimes["MARKET_TREND"] == "neutral"
    assert "policy_version" not in regimes
