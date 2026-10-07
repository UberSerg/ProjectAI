"""Macro / market-regime vocabulary and predeclared thresholds (Intelligence Stack V1).

Thresholds are transparent first-pass rules. They are NOT calibrated against future
returns or walk-forward Sharpe. Changing semantics requires a version bump.
"""

from __future__ import annotations

POLICY_VERSION = "macro_regime_thresholds_v1"
SNAPSHOT_BUILDER = "MacroRegimeSnapshotV1"

STATUS_READY = "READY"
STATUS_PARTIAL = "PARTIAL"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_UNKNOWN = "UNKNOWN"

# Regime axes (keys in MacroSnapshotV1.regimes).
REGIME_RATE = "RATE"
REGIME_MARKET_TREND = "MARKET_TREND"
REGIME_VOLATILITY = "VOLATILITY"
REGIME_FX = "FX"

REGIME_AXES: tuple[str, ...] = (
    REGIME_RATE,
    REGIME_MARKET_TREND,
    REGIME_VOLATILITY,
    REGIME_FX,
)

# RATE labels
RATE_EASING = "easing"
RATE_NEUTRAL = "neutral"
RATE_TIGHTENING = "tightening"
RATE_UNKNOWN = "unknown"

# MARKET_TREND labels
TREND_RISK_ON = "risk-on"
TREND_NEUTRAL = "neutral"
TREND_RISK_OFF = "risk-off"
TREND_UNKNOWN = "unknown"

# VOLATILITY labels
VOL_CALM = "calm"
VOL_ELEVATED = "elevated"
VOL_STRESS = "stress"
VOL_UNKNOWN = "unknown"

# FX labels (RUB vs USD; positive USD/RUB change = RUB weakening)
FX_STRENGTHENING = "strengthening"
FX_STABLE = "stable"
FX_WEAKENING = "weakening"
FX_UNKNOWN = "unknown"

# Series / instrument codes reused from market universe.
SERIES_KEY_RATE = "KEY_RATE"
SERIES_USD_RUB = "USD_RUB_CBR"
SERIES_RUONIA = "RUONIA"
INDEX_IMOEX = "IMOEX"
INDEX_RGBI = "RGBI"

TIMEFRAME_DAILY = "1d"

# Lookbacks (calendar trading bars for candles; series uses observation dates).
WINDOW_RETURN_20D = 20
WINDOW_RETURN_60D = 60
WINDOW_VOL_20D = 20
WINDOW_FX_20D = 20
RATE_CHANGE_LOOKBACK_DAYS = 90

# RATE: material policy move in percentage points over lookback.
RATE_EASE_PP = -0.25
RATE_TIGHTEN_PP = 0.25

# MARKET_TREND: IMOEX simple return over 20 sessions.
TREND_RISK_ON_MIN = 0.03
TREND_RISK_OFF_MAX = -0.03

# VOLATILITY: sample std (ddof=1) of daily log returns over 20 sessions.
# Absolute bands — not ratio-to-history (avoids full-sample look-ahead calibration).
VOL_CALM_MAX = 0.008
VOL_STRESS_MIN = 0.015

# FX: USD/RUB simple pct change over ~20 FX observations.
FX_STRENGTHEN_MAX = -0.02  # USD falls → RUB strengthens
FX_WEAKEN_MIN = 0.02

# Breadth: share of liquid equities with positive 20d return.
BREADTH_MIN_NAMES = 20
BREADTH_EQUITY_LOOKBACK = 21  # need 20 returns → 21 closes

KNOWN_AT_QUALITY = "DATE_ONLY"

LIMITATION_NO_YIELD_CURVE = (
    "gov_yield_curve not available: investment.bond_market_snapshots has no YTM "
    "and RGBI is a price index, not a government yield curve"
)
LIMITATION_NO_SHORT_LONG = (
    "short_long_spread not available: RUONIA series empty and no OFZ tenor yields "
    "for an honest short/long reconstruction"
)
LIMITATION_RGBI_PROXY = (
    "rgbi_return_20d is a government-bond PRICE index proxy, not a yield level/curve"
)
LIMITATION_BREADTH_THIN = (
    "breadth uses only equities with sufficient local 1d candle history; "
    "not full MOEX advance/decline statistics"
)
LIMITATION_KEY_RATE_PIT = (
    "KEY_RATE known_at is DATE_ONLY (CBR observation date); no exact publication timestamp"
)
LIMITATION_FX_PIT = (
    "USD_RUB_CBR known_at is DATE_ONLY (CBR FX observation date)"
)
