# Risk & Opportunity Engine V0

## Purpose

Explain **why** Kraken chose a capital structure among Equity / Fixed Income / Cash.

```text
Market Data
    |
Analytics / Models / Fixed Income
    |
Opportunity Assessment
    |
Risk Assessment
    |
Asset Allocation / Investment Decision
    |
Portfolio Preview
```

Does **not** replace Prediction models, Asset Allocation Policy, Simulator, or Shadow.

## Why prediction ≠ decision

A forecast is an opportunity input. The decision engine still applies:

- hurdle / required premium;
- calibration honesty (`UNKNOWN` when unproven);
- deterministic risk budget constraints;
- human-readable reason codes.

No magic investment score collapses these roles.

## Equity calibration

Read-only analysis of matured `learning.forward_prediction_outcomes`
(`EXPECTED_RETURN` only). Buckets by predicted return; reports bias, MAE, hit rate,
sample size, uncertainty. Never invents confidence. A single metric never proves
“the model is bad”.

## Fixed Income opportunity

Observed yield is not guaranteed profit. UI always reminds that high yield may
reflect high credit / liquidity risk. Support status and data quality gate the sleeve.

## Risk budget

Deterministic profiles: `CONSERVATIVE_ALLOCATION_V0`, `BALANCED_ALLOCATION_V0`,
`GROWTH_ALLOCATION_V0`. Not historically optimized. Inputs considered: volatility,
drawdown, concentration, liquidity, data quality (when provided).

## Investment decision

`InvestmentDecisionEngine` combines opportunities + risk budget + market context into
weights with human-readable reasons. Cash is a valid outcome when opportunities are
unproven or blocked by constraints.

## Out of scope (V0)

No ML training, Candidate V2, Dataset V3, broker, real money, Forward/Shadow mutation,
policy optimization, taxes.
