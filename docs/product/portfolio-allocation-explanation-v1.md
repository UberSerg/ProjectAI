# Portfolio Allocation Explanation V1

Investor-facing explainability for Portfolio Builder / Candidate.

## What it answers

After «какой портфель собрать?» Kraken explains **why** target and actual differ.

Example:

- Target: Equity 25% / FI 65% / Cash 10%
- Actual may show much higher Cash when FI sleeve cannot be filled honestly.

## Behavior (unchanged)

Composition, Risk Gate, concentration caps, `research_fi_v1`, Prediction and Policy are **not** modified.

Cash that cannot be placed into eligible instruments under concentration limits stays Cash — deliberate safety, not a failure to «invest fully».

## Response field

`portfolio_explanation` on `POST /portfolio/candidate/preview`:

- target / actual / deltas
- cash breakdown: strategic / constraint_unallocated / lot_rounding
- messages with Russian investor copy
- constraints (eligible count, required names, max single position)

Legacy `cash.lot_remainder_rub` is preserved (may still include constraint + lot). Prefer the new breakdown fields for UI.

## UI

«Портфель Kraken» → block **Почему именно такой портфель** with Plan vs Actual bars and explanation cards.
