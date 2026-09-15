# Portfolio Builder V1

Investor-facing productization of the existing concrete Portfolio Candidate.

## Scenario

User enters capital in RUB (default `100000`) → Kraken returns a lot-aware research portfolio:

Equity / Fixed Income / Cash with concrete instruments, whole lots, cash remainder.

## Source of truth

Does **not** introduce a new investment strategy.

Uses:

- `POST /api/v1/portfolio/candidate/preview` (`build_portfolio_candidate`)
- Opportunity → Sleeve Allocation → Concrete Selection → Risk Gate → Integer Lots
- CBR hurdle from existing provider
- Bond dirty pricing via existing `calculate_bond_purchase`
- Equity LOTSIZE via `resolve_equity_lot_sizes` (no silent `LOTSIZE=1`)

Optional request alias: `capital_rub` → same as `capital`.

Capital bounds: `0 < capital ≤ 100_000_000`.

## What capital changes

Only concrete lot sizing and cash remainder for the same Candidate policy.

Capital does **not** change:

- Prediction model
- Dataset V2
- Candidate selection policy versions
- `research_fi_v1`
- Shadow

## UI

- Route: `/portfolio/candidate` (alias `/portfolio/builder`)
- Nav label: «Собрать портфель»
- Overview CTA: «Собрать портфель»

## Correlations

Deferred. Relations V2 / correlation pair APIs exist for research overlays but are not wired into Candidate construction. Recommended follow-up: `Portfolio Relations Visualization V1`.

## Why target ≠ actual

See `docs/product/portfolio-allocation-explanation-v1.md`. High Cash is often intentional: FI sleeve cannot be filled without violating concentration / eligibility — capital stays in Cash.

## Disclaimer

Research / advisory Candidate only. No broker execution.
