# Investment Decision Engine

## Prediction ≠ decision

A model forecast is an **input**, not a capital order. The decision engine applies hurdle
comparison, calibration honesty, and risk budget constraints before proposing sleeve weights.

## Risk is separate

Opportunity answers “what might we earn?”. Risk budget answers “how much pain is allowed?”.
Mixing them into one opaque score hides trade-offs and invents fake confidence.

## Cash can be correct

When equity premium is weak, calibration is unknown, or FI credit quality is blocked by a
conservative budget, holding cash relative to the CBR hurdle is a valid research outcome —
not a failure to “always invest”.

## Research comparison

Compare Equity only / Fixed Income only / Allocation Policy / CBR benchmark side by side.
Do **not** auto-declare a winner. Ask: did the result justify the risk?

## Profiles (deterministic)

- `CONSERVATIVE_ALLOCATION_V0` — minimize risk; unknown credit blocked
- `BALANCED_ALLOCATION_V0` — middle constraints
- `GROWTH_ALLOCATION_V0` — higher equity cap

Not selected by backtest optimization.
