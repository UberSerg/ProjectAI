# Relations Engine V1

## Purpose

Relations Engine finds and historically stores **statistical relations** between market factors.

It does **not** issue BUY/SELL recommendations. It measures market structure for later ML / agents.

## Architecture (ML-ready)

```text
Analytics features (log_return_1d, series levels)
        ↓
Relation Inputs (instrument_feature | series_feature)
        ↓
RelationCalculator (pure, in-memory)
        ↓
relation_snapshots (as_of_date) + relation_lag_metrics
```

Key property: every snapshot has an explicit **`as_of_date`**. Training datasets can reconstruct the market structure known at historical time D without look-ahead.

## Relation inputs

Stored in `analytics.relation_inputs`.

| Family (V1) | Example code | Transform |
|-------------|--------------|-----------|
| `instrument_feature` | `instrument:SBER:log_return_1d` | Analytics `log_return_1d` |
| `series_feature` (FX) | `series:USD_RUB_CBR:pct_change` | as-of level → pct_change |
| `series_feature` (rates) | `series:KEY_RATE:absolute_change` | as-of level → absolute_change |

**Do not correlate raw prices.** Instrument base input is `log_return_1d`.

Series changes are computed as:

1. as-of join of **levels** onto the market calendar;
2. difference / pct of consecutive as-of levels.

This avoids silently forward-filling the last rate *change*.

Schema allows future families; V1 does not ship empty stubs for unused types.

## Relation set

`basic_relations` v1 parameters (JSONB, not hardcoded in services):

- `correlation_methods`: pearson, spearman
- `windows`: 20, 60, 120
- `lead_lags`: 1..5
- `minimum_coverage_ratio`: 0.8
- `stability_subwindow`: 20
- `exclude_invalid_features`: true
- `exclude_price_discontinuities`: true

## Snapshots & lag semantics

Zero-lag pairs are unordered (`input_a_id < input_b_id`); no A↔A; no duplicate A↔B / B↔A.

Lead-lag stores **both directions** for **all** lags 1–5 in `relation_lag_metrics`:

> **leader(t)** correlated with **follower(t + lag)**

Best lag = max |corr|; tie-break = smaller lag.

### Example: BRENT → LKOH lag 2 (illustrative)

If oil returns lead Lukoil returns by two trading observations:

| Leader | Follower | Lag | Interpretation |
|--------|----------|-----|----------------|
| BRENT log_return | LKOH log_return | 2 | oil(t) co-moves with LKOH(t+2) |

This is a **statistical** lead, not causation. Confounders, regimes, and reverse causality are out of scope for V1.

## No look-ahead

For `as_of_date = D`, zero-lag and lead-lag use only observations with dates ≤ D.

Regression tests poison future values after D and assert identical correlations.

## Workflows

| Workflow | API | Celery |
|----------|-----|--------|
| `RelationsComputeLatest` | `POST /api/v1/relations/compute-latest` | `projectai.relations_compute_latest` |
| `RelationsBackfill` | `POST /api/v1/relations/backfill` | `projectai.relations_backfill` |

Backfill cadence: `DAILY` | `WEEKLY` (default **WEEKLY** for multi-month history).

`NO_CHANGES` when LATEST as_of / relation set version / source watermark already computed.

Events: `relations.compute_*`, `relations.backfill_*`, `relations.calculation_failed`, `relations.insufficient_samples`, `relations.input_resolution_failed`.

Diagnostics block: `=== RELATIONS ===`.

## API

`/api/v1/relations`: overview, sets, inputs, runs, snapshots (+ filters), snapshot lags, pair detail, compute-latest, backfill.

Prefer `/pairs/detail` for pair + lag profile (avoids N+1).

## UI

Sidebar **Связи** → overview, top relations table, filters, pair explorer (lag table), disclaimer. No network graph.

## Limitations (honest)

V1 does **not** include:

- Granger causality / causal discovery
- ML training on relations
- regime detection
- fundamental intelligence
- Technical Agent / Recommendations
- automated trading signals
- mechanical-adjusted inputs (`basic_relations` v1 uses Analytics `log_return_1d` on RAW
  close). Future versions should stop treating split/denomination jumps as correlation
  shocks, without auto-erasing dividend gaps (ADR 0005).

**Performance (current universe ~48 inputs):** RelationsComputeLatest ≈ **45 s**; historical WEEKLY backfill (~90–120 days, ~18 as-of) ≈ **10 min**. Acceptable for asynchronous V1. Further profiling only if the universe grows materially.

**Orphan RUNNING workflows:** if the Celery worker dies mid-run, `system.workflows` may stay `RUNNING` forever. Diagnostics flags RUNNING older than ~15 minutes as possibly stale (shows age + progress meta). Acceptance watchdog uses timeout/stale on workflow `meta` heartbeats. Operators abort manually (set ERROR) — no automatic recovery framework in V1.

Parameters and snapshot history are designed so those stages can consume Relations later without rewriting storage.
