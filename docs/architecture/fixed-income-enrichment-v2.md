# Fixed Income Enrichment V2

## Goal

Async enrichment of MOEX bonds (terms, cashflows, market snapshots) without changing the
Candidate / Opportunity strategy universe.

## Strategy pin: `research_fi_v1`

At migration `20260908_0022` (and idempotent seed), `market.universe_memberships` receives
`research_fi_v1` = instruments that **already had** `investment.bond_terms` (bounded sample).

- `load_fixed_income_candidates` and Opportunity / allocation FI aggregates **only** use this pin.
- Enrichment may add BondTerm / cashflows for any catalog bond.
- Manual Portfolio and Shadow valuation may use **any** enriched bond.
- Growing the Candidate pool requires an **explicit universe version bump** (e.g. `research_fi_v2`).

## Queue

Table `market.instrument_enrichment_jobs` — upsert status row per `(instrument_id, kind)`.

Kinds: `FIXED_INCOME_TERMS` | `FIXED_INCOME_CASHFLOWS` | `FIXED_INCOME_MARKET` | `DIVIDEND_HISTORY`

Priorities (lower = sooner):

| P | Meaning |
|---|---|
| 0 | Manual Portfolio + Shadow bond positions / Candidate selections |
| 1 | Newly discovered bonds from Instrument Master |
| 2 | OFZ |
| 3 | Other bonds |
| 4 | Inactive |

## Invariants

- Reuse `MoexBondClient` + `ingest_bonds` helpers / `calculate_bond_purchase` (no dirty-price fork).
- `FACEUNIT=SUR` → canonical `RUB`.
- Source failure / empty bondization **never wipes** good existing terms.
- Cashflows idempotent via unique constraint; redemption + final amort not double-counted in projections.
- `known_at_quality = CURRENT_STATE_ONLY` retained.
- Does **not** mutate Dataset V2 / training / `research_fi_v1` membership.

## Hooks

- End of Instrument Master bond upsert → enqueue FI kinds.
- Manual Portfolio `add_position` for a bond → P0 enqueue.
- Startup (optional): P0 enqueue only when `FI_ENRICHMENT_ENABLED` + `FI_ENRICHMENT_STARTUP_P0`.

## Celery

- Task `enrich_fixed_income_instruments` (+ scheduled when enabled).
- Bounded `FI_ENRICHMENT_BATCH_SIZE` so EOD / intraday are not starved.
- Redis lock `projectai:fi_enrichment:lock`.

## API

- `GET /api/v1/fixed-income/coverage`
- `POST /api/v1/fixed-income/enrichment/run`
- Artifact: `.tmp/fixed-income-dividend-enrichment-v2/fi-coverage.json`
