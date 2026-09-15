# Portfolio Relations Visualization V1

Read-only correlation heatmap for instruments in the current Kraken Portfolio Candidate.

## What the user sees

On **Портфель Kraken**, after composition / Plan vs Actual / «Почему именно такой портфель»:

**Связи внутри портфеля** — pairwise **корреляция доходностей** (not causation).

## Source metric (authoritative Relations)

- Feature: `log_return_1d` (daily log returns from Analytics / Relations inputs)
- Method shown: **Pearson** (Spearman also stored on snapshots; UI primary = Pearson)
- Default window: **60** trading days (existing Relations default; also 20/120 exist)
- Coverage rule: existing Relations `minimum_coverage_ratio` 0.8
- EOD / daily cadence — not intraday
- Calculation: **persisted** `analytics.relation_snapshots` — no recompute on page view
- PIT: snapshots already carry `as_of_date`; matrix uses **latest** available as_of per pair for the window

## API

`POST /api/v1/relations/portfolio`

Body: `{ "symbols": ["SBER", ...], "window": 60 }` (max 12 symbols).

Returns matrix cells, instrument readiness, summary (strongest / lowest / avg |corr|), metric metadata.

Cash / sleeve labels are stripped. Unsupported or missing pairs → `pearson: null` (UI **N/A**, never coerced to 0).

## Interpretation (UX-only)

Descriptive bands for copy/heatmap (not Candidate Policy):

- high positive: ≥ 0.70
- moderate: 0.40–0.70
- weak: |r| < 0.40
- negative: ≤ −0.40

Do not treat these as risk gate or rebalance rules.

## Limitations

- Fixed Income often missing from Relations universe → N/A cells with reason
- No diversification score, Markowitz, or network graph in V1
- Visualization does **not** change Candidate, allocation, Risk Gate, or Prediction

## Correlation ≠ causation

UI copy states historical co-movement of returns only; it can change and does not guarantee future behaviour.
