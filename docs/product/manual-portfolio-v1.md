# Manual Portfolio V1

## Purpose

Single primary user-declared portfolio for valuation, concentration, advisory compare vs Portfolio Candidate, and cash-safe lot rebalance advice. No broker execution.

## Persistence

Schema `portfolio` (shared with Historical Simulator):

- `manual_portfolios` — cash RUB, version, source=`MANUAL`
- `manual_positions` — `instrument_id`, units, optional average price, `non_standard_lot`

## Valuation

- Equity / fund: units × LAST (intraday Redis) or EOD close fallback
- Bonds: dirty = clean% × nominal + NKD via `calculate_bond_purchase` — never treat 95.5 as RUB
- Unsupported positions are **not** valued as zero

## Analysis

`GET .../analysis` returns NAV, allocation, issuer concentration, advisory risk findings (not a BLOCKED gate), coverage %, quality `LIVE|PARTIAL|STALE`.

Suggested actions: `KEEP|INCREASE|REDUCE|EXIT|REVIEW|NO_VIEW` from risk/coverage/candidate — no new ML.

## Compare / rebalance

- Compare: weights vs `/portfolio/candidate/current`. `NOT_IN_CANDIDATE` ≠ SELL
- Rebalance: advisory only via `build_lot_order_plan`; scale candidate weights to user NAV; cash-safe; no persisted orders; FI exact mismatch → `REVIEW`

## Intraday

`resolve_intraday_universe` unions Manual Portfolio position instrument ids with Shadow universe.
