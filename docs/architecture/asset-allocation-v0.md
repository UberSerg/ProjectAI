# Asset Allocation Foundation V0

## Purpose

Kraken is not required to always buy equities. Asset Allocation is the research layer that
answers: **where should capital sit among Equity Alpha, Fixed Income, and Cash?**

```text
Market Data
    |
Analytics / Fundamentals / Signals
    |
Expected Opportunity
    |
Hurdle Comparison
    |
Asset Allocation
    |
---------------------
|         |          |
Equity   Fixed      Cash
Alpha    Income
|
Risk Management
|
Execution
```

Asset Allocation **uses** model outputs; it does **not** replace models.

## Domain

- `AllocationContext` — as_of, capital, CBR hurdle, opportunities, risk/liquidity, constraints
- `AllocationDecision` — sleeve weights + reason_codes + Russian explanation (no magic score)
- `EquityOpportunity` / `FixedIncomeOpportunity` / `CashOpportunity`
- `AssetAllocationPolicy.decide(context) -> AllocationDecision`

## Research policies V0

| Id | Role |
|----|------|
| `STATIC_100_EQUITY` | Benchmark 100% equity |
| `STATIC_100_FIXED_INCOME` | Benchmark 100% FI |
| `STATIC_100_CASH` | Cash / CBR hurdle benchmark |
| `CBR_HURDLE_GATE_V0` | Shrink equity when expected excess < required premium |

No historical weight optimization.

## 100k preview

`AllocationDecision` → target weights → existing integer-lot allocator → cash remainder.

## Out of scope

ML, RL, broker, real money, Forward/Shadow/Prospective mutation, mass backtests.
