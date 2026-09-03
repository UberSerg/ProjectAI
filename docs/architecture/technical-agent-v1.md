# Technical Agent V1

## Purpose

Technical Agent V1 is ProjectAI’s first full analytical agent: deterministic technical features + a transparent rule-based model that produces historical **technical state** (score / direction / confidence / factor contributions) for any as-of date `t`.

It is **not** a trading recommendation, not ML, and not an Expert/LLM layer.

## Data flow

```text
Market OHLC candles
    ↓
Analytics basic_daily v1  (instrument_features_daily)   ← read only
    ↓
TechnicalFeatureCalculator  (pure)
    ↓
technical_daily v1  → analytics.instrument_technical_features_daily
    ↓
TechnicalSignalService
    ↓
Frozen TechnicalModelInput
    ↓
RuleBasedTechnicalModel (rules_v1)  ← pure, no DB
    ↓
technical.signals_daily + technical.runs
```

## TechnicalSignalService

Application orchestration:

1. Resolve model + feature set versions  
2. Load PIT basic + technical feature rows  
3. Merge quality context  
4. Build frozen `TechnicalModelInput`  
5. Call `TechnicalModel.predict(input)`  
6. Persist `TechnicalModelOutput`

## TechnicalModel purity

`TechnicalModel.predict` must **not** query PostgreSQL, Redis, HTTP, or Celery.

Identical `(input, model_version, model_config)` ⇒ identical output.

## technical_daily v1

Registered in `analytics.feature_sets` (`code=technical_daily`, `version=1`).

Immutable semantics. Formula changes require `technical_daily` v2.

Stored derived columns (wide table `analytics.instrument_technical_features_daily`):

- `sma20`, `sma20_distance`
- `ema20`, `ema20_distance`
- `rsi14`
- `atr14`, `atr14_pct`
- quality: `has_sufficient_history`, `is_valid`, `quality_flags`
- lineage: `source_basic_feature_id`

Absolute SMA/EMA/ATR are stored for audit; ML-facing distances/pct are primary.

Analytics features (`return_*`, volatility, drawdown, volume_*) are **not** recomputed — they are read from `basic_daily` v1.

## Formulas

### SMA20

Mean of the last 20 **trading** closes including `t`.  
If fewer than 20 observations → NULL.

`sma20_distance = close(t) / SMA20(t) - 1`  
If SMA20 ≤ 0 → NULL + quality flag.

### EMA20

pandas-compatible `ewm(span=20, adjust=False, min_periods=20)`:

- `alpha = 2 / 21`
- seed with first close, recursive update
- first 19 values NULL

`ema20_distance = close(t) / EMA20(t) - 1`

### RSI14 (Wilder)

```text
delta = close(t) - close(t-1)
gain = max(delta, 0); loss = max(-delta, 0)
avg_gain/loss_0 = mean of first 14 deltas
avg(t) = (avg(t-1) * 13 + value(t)) / 14
RS = avg_gain / avg_loss
RSI = 100 - 100 / (1 + RS)
```

Edges: loss=0&gain>0 → 100; gain=0&loss>0 → 0; both 0 → 50.  
Insufficient history → NULL (never 0-fill).

### ATR14 (Wilder)

```text
TR[0] = high - low
TR[t] = max(high-low, |high-prev_close|, |low-prev_close|)
ATR first = mean(TR[0:14]) at index 13
ATR(t) = (ATR(t-1)*13 + TR(t)) / 14
atr14_pct = ATR14 / close
```

OHLC invariants checked; invalid bars flagged (`invalid_ohlc`).

## rules_v1

| Field | Value |
|-------|-------|
| model_code | `rules` |
| model_version | `1` |
| Display | `rules_v1` |

Config (hashed into lineage):

```json
{
  "trend_weight": 0.35,
  "momentum_weight": 0.35,
  "rsi_weight": 0.20,
  "volume_weight": 0.10,
  "distance_scale": 0.05,
  "return_scale": 0.10,
  "rsi_center": 50,
  "rsi_scale": 20,
  "volume_scale": 3,
  "bullish_threshold": 0.20,
  "bearish_threshold": -0.20,
  "momentum_return_5d_weight": 0.6,
  "momentum_return_20d_weight": 0.4
}
```

### Score

```text
trend = avg(clip(sma20_distance/0.05), clip(ema20_distance/0.05))
momentum = 0.6*clip(return_5d/0.10) + 0.4*clip(return_20d/0.10)
rsi = clip((rsi14-50)/20, -1, 1)
volume = 0 if z<=0 else sign(momentum)*clip(z/3, 0, 1)

score = weighted average over available factors, clamped [-1, 1]
```

Missing factors are skipped and weights renormalized; coverage lowers confidence.

### Direction

- score ≥ +0.20 → `bullish` (Бычье)
- score ≤ −0.20 → `bearish` (Медвежье)
- else → `neutral` (Нейтральное)

### Confidence

Not P(profit):

```text
coverage_ratio = available_required / 4
agreement = 0.5 + 0.5 * |score|
quality_factor = 0 if critical/invalid; 0.7 if warnings; else 1.0
confidence = clip(coverage * agreement * quality_factor, 0, 1)
```

## Quality

`price_discontinuity` from Market DQ / Analytics flags propagates into technical rows and invalidates signals (confidence 0, direction neutral). No silent repair of raw prices.

## No look-ahead

Only observations with date ≤ `t`. Covered by regression tests that mutate future candles without changing features/signals at `t`.

## Incremental / warm-up

**Strategy:** `full_history_tail_persist`

- Load **all** available OHLC for the instrument (ensures exact Wilder/EMA state).
- Calculate full series in memory.
- Persist only the requested output window (backfill range or update tail with small safety overlap).

This proves incremental equivalence with full-history calculation without a recursive state machine.

## Lineage

Each signal stores:

- `model_code`, `model_version`, `model_config_hash`
- `basic_feature_set_id`, `technical_feature_set_id`
- `source_basic_feature_id`, `source_technical_feature_id`
- `as_of_date`, `run_id`
- run `source_watermark` (latest market date, feature set refs, basic latest date)

`learning.model_registry` is **not** used for rules_v1 (foundation-only table; no ORM/API). Lineage lives on runs/signals. Future CatBoost can register there without changing the TechnicalModel port.

## ML compatibility

Replace `RuleBasedTechnicalModel` with `CatBoostTechnicalModel` implementing the same port.  
`TechnicalSignalService`, workflows, signal schema, and UI contracts stay stable. ML receives frozen input only.

## Limitations

- rules_v1 is a heuristic baseline, not claimed alpha  
- Score ≠ expected return; confidence ≠ profit probability  
- No ML / backtest / optimization  
- No Relations inside rules_v1  
- No regime / fundamentals / news / intraday  
- No adjusted-price engine (`technical_daily` v1 / `rules_v1` use RAW OHLC). Future
  mechanical-adjusted indicators need a **new version** so split/denomination artefacts
  do not look like crashes; dividend gaps must not be auto-erased (ADR 0005).  
- Not a BUY/SELL recommendation  
