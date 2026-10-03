# Research Evidence Engine V1

Research-only machinery that turns Dataset V3/V4 builds into **evidence artifacts**,
not into a production Candidate.

This milestone does **not** promote models, mutate Shadow, rewrite Personal Decision
Memory, change Daily Decision, or execute broker orders. Technical `VERSION` stays
`1.0.0`. Product micro-release stays **Kraken 1.03**. There is no Kraken 1.04 here.

## Purpose

Separate four statements Kraken must not conflate:

1. We added more features (Dataset V4 X).
2. We have chronological out-of-sample **historical** model diagnostics.
3. That ranking signal was run through a long-only **economic research simulation**.
4. We have **prospective** observations after real recommendations (Forward Outcomes + PDM).

The UI shows those layers. It does not emit `overall_accuracy`, `kraken_score`,
`master_score`, or `production_readiness_score`.

## Historical vs prospective evidence

Historical evidence is a walk-forward research experiment on frozen DatasetRuns.
Prospective evidence is a read-only aggregation of outcomes that matured after
decisions/predictions already existed.

**Do not merge the two classes statistically.** No combined Kraken accuracy.

```text
Dataset V3/V4
      ↓
Chronological OOS
      ↓
Ablation / Stability
      ↓
Economic simulation
      ↓
Historical Evidence

Forward Outcomes + PDM
      ↓
Prospective Evidence

Historical + Prospective
      ↓
Evidence UI
```

## V3/V4 fair experiment

Reuse Dataset V4 foundation contracts:

- same `historical_equity_universe_v2`
- same mechanical 20d price-return labels
- exact sample identity (`instrument_id`, `as_of_date`)
- V4 only adds PIT fundamental/event features (`NATIVE_NAN`)

Mismatch is `FAIR_CONTRACT_FAIL`. Model and economics steps must not run after that.

Experiment identity (`ResearchEvidenceExperimentV1`) is a SHA-256 of canonical
semantic JSON. Runtime timestamps are metadata only.

## Regression vs ranking

| Semantic | Target / score | Allowed metrics |
|---|---|---|
| REGRESSION | `forward_return_20d` (research expected-return-like estimate) | n, MAE, RMSE, R², directional accuracy, positive precision, rank IC, top/bottom spread |
| RANKING | `RANKING_SCORE` (not return %) | n, rank IC, median IC, IC dispersion, positive IC date share, top/bottom spread |

Ranking must not expose MAE/RMSE/R². Ranking scores must not be reported as expected return.

Wording: **CHRONOLOGICAL OOS RESEARCH**. Do not call a previously inspected window
a pristine final holdout unless the repository can prove it was untouched.

## Ablation

Same V4 rows, same `y`, same folds, same hyperparameters, same seed. Only the
feature mask changes. Missing stays NaN (never coerced to 0). Samples are not
dropped because a group is empty.

- BASE — V3 feature set
- BASE + FUNDAMENTALS — event columns masked to NaN
- BASE + EVENTS — fundamental columns masked to NaN
- V4 FULL — all V4 features

Paired date-level deltas (e.g. IC_V4 − IC_BASE) use bootstrap-by-trading-date.
Insufficient dates → `INSUFFICIENT`. No fabricated p-values. No “V4 wins” verdict.

## Chronological OOS

Expanding folds. For every train boundary:

- `as_of_date < validation_start`
- `target_date_20d < validation_start` (label purge)

No randomized split. Hyperparameters stay frozen (`CATBOOST_HYPERPARAMETERS` /
ranker YetiRank pins). No Optuna.

## Cost-aware economic simulator

Research portfolio, not Shadow and not Personal Portfolio.

- EOD signal at session T → next eligible session **official OPEN**
- missing OPEN → `EXECUTION_PRICE_UNAVAILABLE` (never silent close)
- long-only, no leverage, cash first-class
- `position_sizing = FRACTIONAL_RESEARCH_WEIGHTS`
- rebalance every 20 trading sessions (predeclared)
- top 20% equal weight of eligible historical universe; thin cross-section → cash
- OOS predictions only, with fold/train-cutoff provenance
- splits handled mechanically; **dividends excluded**; semantic `PRICE_RETURN`
- costs: `ASSUMED_ALL_IN_COST_BPS_PER_SIDE` ∈ {0, 10, 30, 50} — assumptions, not
  historical broker invoices
- primary benchmark: eligible-universe equal-weight on the same dates/costs/execution

If an exit cannot be priced: `UNRESOLVED_EXIT` and artifact `PARTIAL`.

## PRICE_RETURN limitation

Labels and simulator PnL are mechanical price returns. Universe-wide Total Return
is still incomplete. Dividends are not cash in this engine.

## Transaction-cost assumptions

Sensitivity scenarios only. They are not “actual Sber fees”. Liquidity impact is
not modelled. Fractional weights are not lot-realistic.

## No auto-promotion

`PIT_DAILY_CORE_ACTIVE_VERSION = 1`. Candidate V0/V1 stay on Dataset V2.
`persist_registry` is false. No Candidate V2. No Dataset V5.

## Evidence API

OWNER research routes (presentation role is UI-level; do not broaden IAM):

- `GET /api/v1/research/evidence/overview`
- `POST /api/v1/research/evidence/run`
- `GET /api/v1/research/evidence/{experiment_id}`
- `GET /api/v1/research/evidence/{experiment_id}/economics`
- `GET /api/v1/research/evidence/prospective`

Overview returns **aggregates**. Prediction rows are not dumped to the UI.

Heavy runs use existing Workflow / Celery — no new queue product.

## UI

Route `/research/evidence` under Исследования («Доказательства»).

Badge: **RESEARCH ONLY**. Never LIVE READY / PRODUCTION READY / AUTO TRADE.

Historical and prospective blocks are visually separated. Limitations card is
mandatory.

## Known limitations

- Total Return still incomplete; dividends excluded
- bank/FI fundamentals limited by FNS RAS support
- historical delisted coverage is partial
- `CURRENT_ONLY` issuer identity is weaker than `DATED_WINDOW`
- fractional research sizing; assumed all-in costs; no market-impact model
- incomplete delisting execution may mark economics `PARTIAL`
- no automatic Candidate / Shadow / Daily Decision change
- prospective samples may be `INSUFFICIENT_SAMPLE`; a confirmed PersonalOperation
  link is not causality
