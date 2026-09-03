# Analytics Feature Layer V1

## Purpose

Analytics Layer stores **derived** market features separately from **factual** market data:

- `market.*` — source candles, series values, quality issues
- `analytics.*` — versioned computed features

## Feature set versioning

Feature semantics are immutable per `(code, version)`.

- **basic_daily v1** — RAW close/volume (active)
- **basic_daily v2** — PIT mechanical-adjusted close/volume for SPLIT / REVERSE_SPLIT
  only. Not dividend-adjusted. Not total return. Not active by default.

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

- `basic_daily` v1 uses **RAW** close. Mechanical-adjusted features live in **v2**, not here.
- Unresolved `abnormal_price_jump` flags discontinuities; it does **not** classify split vs
  crash vs dividend. Raw candles are never modified.

## H4A — basic_daily v2 (mechanical adjustment)

Formulas are the same as v1, but close/volume are first scaled onto the share basis of
sample date `t` using only `SPLIT` / `REVERSE_SPLIT` with `effective_date <= t`.

- price_adj(d|t) = price_raw(d) / Π factor for events with `d < event_date <= t`
- volume_adj(d|t) = volume_raw(d) × that product
- factor = after / before
- A future event (`effective_date > t`) must not change X(t)
- Dividend gaps stay in the series. H3.1 dividend ingest is deferred (no free PIT feed).
- `market.candles` stay RAW. Technical / Relations / Dataset still pin v1.
