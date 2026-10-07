"""Focused pure tests for macro metrics + regime thresholds (no DB/network)."""

from __future__ import annotations

import math
from datetime import date

from app.modules.intelligence.macro.constants import (
    FX_STABLE,
    FX_STRENGTHENING,
    FX_WEAKENING,
    POLICY_VERSION,
    RATE_EASING,
    RATE_NEUTRAL,
    RATE_TIGHTENING,
    TREND_NEUTRAL,
    TREND_RISK_OFF,
    TREND_RISK_ON,
    VOL_CALM,
    VOL_ELEVATED,
    VOL_STRESS,
)
from app.modules.intelligence.macro.metrics import (
    breadth_advance_share,
    last_nonzero_change,
    pct_change_from_levels,
    realized_vol_log,
    series_level_change,
    simple_return,
)
from app.modules.intelligence.macro.regimes import (
    classify_fx,
    classify_market_trend,
    classify_rate,
    classify_regimes,
    classify_volatility,
)


def test_simple_return_and_vol() -> None:
    closes = [100.0, 101.0, 102.0, 101.5, 103.0]
    assert simple_return(closes, 1) is not None
    assert abs(float(simple_return(closes, 4)) - (103.0 / 100.0 - 1.0)) < 1e-12
    assert simple_return(closes, 10) is None

    vol = realized_vol_log(closes, 4, ddof=1)
    assert vol is not None and vol > 0.0
    # Manual check: 4 log returns
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, 5)]
    mean = sum(rets) / 4
    expected = math.sqrt(sum((r - mean) ** 2 for r in rets) / 3)
    assert abs(vol - expected) < 1e-12


def test_series_level_change_and_last_nonzero() -> None:
    points = [
        (date(2026, 1, 1), 16.0),
        (date(2026, 2, 16), 15.5),
        (date(2026, 3, 23), 15.0),
        (date(2026, 7, 27), 14.0),
        (date(2026, 9, 30), 14.0),
    ]
    # 2026-09-30 - 90d → ~2026-07-02; last point on/before cutoff is 2026-03-23 (15.0)
    chg, from_d, to_d = series_level_change(points, as_of=date(2026, 9, 30), lookback_days=90)
    assert to_d == date(2026, 9, 30)
    assert from_d == date(2026, 3, 23)
    assert abs(float(chg) - (14.0 - 15.0)) < 1e-12
    # 2026-09-30 - 200d → ~2026-03-14; last point on/before cutoff is 2026-02-16 (15.5)
    chg200, from200, _ = series_level_change(points, as_of=date(2026, 9, 30), lookback_days=200)
    assert from200 == date(2026, 2, 16)
    assert abs(float(chg200) - (14.0 - 15.5)) < 1e-12
    # Within a short lookback after the last move, change vs baseline on that day is 0
    chg_short, from_short, _ = series_level_change(
        points, as_of=date(2026, 9, 30), lookback_days=30
    )
    assert from_short == date(2026, 7, 27)
    assert chg_short == 0.0

    last_chg, last_d = last_nonzero_change(points)
    assert last_chg == -1.0
    assert last_d == date(2026, 7, 27)


def test_pct_change_and_breadth() -> None:
    fx = [
        (date(2026, 1, i + 1), 100.0 + i) for i in range(25)
    ]
    pct = pct_change_from_levels(fx, 20)
    assert pct is not None
    assert abs(pct - (fx[-1][1] / fx[-(20 + 1)][1] - 1.0)) < 1e-12

    share, n = breadth_advance_share([0.01, -0.02, 0.0, 0.03, None])
    assert n == 4
    assert share == 0.5  # two positives of four


def test_regime_thresholds_predeclared() -> None:
    assert classify_rate(-0.25) == RATE_EASING
    assert classify_rate(-0.5) == RATE_EASING
    assert classify_rate(0.0) == RATE_NEUTRAL
    assert classify_rate(0.25) == RATE_TIGHTENING
    assert classify_rate(None) == "unknown"

    assert classify_market_trend(0.03) == TREND_RISK_ON
    assert classify_market_trend(-0.03) == TREND_RISK_OFF
    assert classify_market_trend(0.0) == TREND_NEUTRAL

    assert classify_volatility(0.007) == VOL_CALM
    assert classify_volatility(0.01) == VOL_ELEVATED
    assert classify_volatility(0.02) == VOL_STRESS

    assert classify_fx(-0.02) == FX_STRENGTHENING
    assert classify_fx(0.02) == FX_WEAKENING
    assert classify_fx(0.0) == FX_STABLE


def test_classify_regimes_from_observations() -> None:
    obs = {
        "key_rate_change_pp": {"value": -0.5},
        "imoex_return_20d": {"value": 0.05},
        "imoex_realized_vol_20d": {"value": 0.006},
        "usd_rub_pct_change_20d": {"value": 0.03},
        "policy_version": POLICY_VERSION,
    }
    regimes = classify_regimes(obs)
    assert regimes["RATE"] == RATE_EASING
    assert regimes["MARKET_TREND"] == TREND_RISK_ON
    assert regimes["VOLATILITY"] == VOL_CALM
    assert regimes["FX"] == FX_WEAKENING
