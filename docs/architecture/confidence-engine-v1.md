# Confidence Engine V1

## Role in the pipeline

```text
Prediction → Calibration → Confidence → Allocation
```

Confidence is a separate layer. It does not retrain models and does not invent probability of profit.

## Levels

| Level | Meaning |
|---|---|
| UNKNOWN | Too few matured outcomes / no calibration history |
| LOW | Some data, but error/bias/stability weak |
| MEDIUM | Adequate sample and relatively stable calibration (research) |
| HIGH | Strict criteria only (large n, low MAE/bias, direction floor) |

Thresholds are documented and **not** historically optimized.

## Why UNKNOWN is valid

If Kraken lacks matured predicted/realized pairs, claiming MEDIUM/HIGH would be fake certainty.
UNKNOWN is the correct research state until evidence exists.

## Effect on allocation

- UNKNOWN / weak calibration → Equity weight capped (reason codes visible)
- Confidence does not auto-zero Equity
- Never replaces Risk Budget or CBR hurdle logic

## Out of scope

No model training, Candidate V2, Dataset V3, Forward/Shadow mutation, broker, real money.
