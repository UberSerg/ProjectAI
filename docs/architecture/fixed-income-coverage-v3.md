# Fixed Income Coverage V3

## Catch-up behaviour

- Enrichment continues when `FI_ENRICHMENT_ENABLED=true` (bounded batches).
- `NO_DATA` jobs: `last_error` classified (`NO_DATA:empty_bondization_no_prior_terms`, `NO_DATA:no_board_row`),
  `next_retry_at = now + 7 days`. Re-enqueue does **not** thrash until retry window.
- System data-coverage exposes pending / success / no_data / failed / partial counts.

## Pin invariant

`research_fi_v1` remains pinned (seed from BondTerm sample at migration 0022; expected count **21**
in current fixtures). Enrichment expands catalog valuation only — **does not** grow Candidate FI pool.

## Catalog V2

`GET /api/v1/bonds` lists Instrument Master bonds with LEFT JOIN terms/cashflows/credit status.
Master-only rows included; opening detail enqueues FI enrichment once (dedupe).
