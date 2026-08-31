# Analytics Feature Layer V1

## Purpose

Analytics Layer stores **derived** market features separately from **factual** market data:

- `market.*` — source candles, series values, quality issues
- `analytics.*` — versioned computed features

## Feature set versioning

Feature semantics are immutable per `(code, version)`. Current active set:

- **basic_daily v1**

Parameters live in `analytics.feature_sets.parameters` (single source of truth).

## Formulas (basic_daily v1)

All rolling windows use **trading observations**, not calendar days.

| Feature | Formula |
|---------|---------|
| return_Nd | close(t) / close(t−N) − 1 |
| log_return_1d | ln(close(t)/close(t−1)), NULL if close ≤ 0 |
| volatility_Wd | std(log_return_1d, window=W, ddof=1), not annualized |
| drawdown_20d | close(t) / max(close in last 20 obs incl. t) − 1 |
| volume_change_1d | volume(t)/volume(t−1) − 1 |
| volume_zscore_20d | (volume(t) − mean(volume[t−20:t−1])) / std(volume[t−20:t−1]) |

Missing history → **NULL**, never zero.

## No look-ahead

Calculations are backward-looking only. Future observations must not affect features at date t.

## Quality propagation

Unresolved `abnormal_price_jump` DQ issues mark affected feature rows with `quality_flags.price_discontinuity`. Raw candles are never modified.

## Point-in-time alignment

- **market ↔ market**: inner join on observation dates
- **market ↔ sparse series**: as-of join (last series value with date ≤ t)

Publication timestamp limitations of Market Data V1 are documented — alignment uses stored observation dates only.

## Workflows

- **FeatureBackfill** — full historical recompute
- **FeatureUpdate** — incremental tail recompute (safety lookback ~25 obs)

Business history: `analytics.feature_runs`. Technical events: `system.event_logs` (same-day only).

## V1 limitations

- No adjusted prices / corporate action correction
- Row-level quality flags when feature-level would be heavier
- No long-term audit log for analytics events
