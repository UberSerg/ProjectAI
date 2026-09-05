# Prediction Calibration V1

## Why a forecast is not a guarantee

When Kraken says “expected return +10%”, that is a model output, not a promise.
Calibration answers: **how often did similar forecasts actually materialize?**

## What calibration does

For Candidate V0 (`prediction_ml_candidate/v0`, semantic `EXPECTED_RETURN`):

1. Take only **EVALUATED** outcomes after **20 trading observations**.
2. Bucket predictions (`lt_0`, `0_2pct`, `2_5pct`, `5_10pct`, `gt_10pct`) — edges frozen as
   `expected_return_buckets_v1`.
3. Report bias = mean(realized − predicted), MAE, direction accuracy, coverage.

Pending outcomes stay pending — never mixed into metrics (no look-ahead).

## Candidate V1

`prediction_ml_candidate/v1_ranker` emits `RANKING_SCORE`. It is **not** a percent return.
V1 uses rank IC / top-quantile realized quality. Return MAE on the score is forbidden.

## Confidence

`PredictionConfidenceEngine` maps evidence → UNKNOWN / LOW / MEDIUM / HIGH with documented
thresholds. HIGH is rare by design. Insufficient sample → UNKNOWN (honest).

## Allocation impact

Allocation must not treat raw prediction as certainty:

`Expected Return + Confidence + Risk → Opportunity Quality`

UNKNOWN confidence can still allow a capped Equity sleeve, but the reason is visible.
