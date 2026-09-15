# Investment Data Readiness V1

**Status:** measurement / gate only  
**Version:** `INVESTMENT_DATA_READINESS_V1`  
**Does not:** mutate Dataset V2, train Candidate V2, reset Shadow, expand `research_fi_v1`

## Purpose

Answer, deterministically:

> Which data domains are quality- and PIT-safe enough to use in a future Dataset V3 — and which are not?

Presence of a table or provider ≠ readiness for research features.

## API

| Endpoint | Role |
|----------|------|
| `GET /api/v1/system/data-coverage` | Existing coverage + embedded `investment_data_readiness` |
| `GET /api/v1/system/data-readiness` | Same readiness payload alone |

No live external scraping on request. Evidence comes from store counts / existing coverage services / architectural rules.

## Status enum

`READY` | `PARTIAL` | `NOT_READY` | `UNKNOWN`

No cosmetic percentages.

## Domains (minimum)

| Domain | Typical status after FNS V1 |
|--------|------------------------------|
| Market EOD | READY |
| Technical | READY / PARTIAL |
| Relations | READY / PARTIAL |
| Fundamentals RAS (FNS) | PARTIAL |
| Bank fundamentals | NOT_READY |
| Dividends | NOT_READY |
| Gross Total Return | NOT_READY |
| Corporate actions (splits) | PARTIAL |
| Fixed Income cashflows | PARTIAL (current-state-only PIT) |
| Corporate credit | NOT_READY |
| CBR / macro | PARTIAL |
| Survivorship-free universe | NOT_READY |

## Dataset V3 gate

Overall status is **not** READY merely because industrial RAS works.

Typical after this milestone:

- `overall_status`: `PARTIAL` (fundamentals gate `READY_FOR_DATASET_DESIGN`)
- Blockers: dividends, total return, survivorship
- Recommended fundamental feature start: `MIN(known_at)` over stored RAS reports (fallback ~2022)

`READY_FOR_BUILD` requires a production dividend lifecycle with `known_at` and entitlement semantics — still absent.

## UI

System → Data Coverage shows:

1. Dataset V3 summary (status, blockers, available, recommended start)
2. Domain readiness table
3. Legacy coverage key-values

## Non-goals

- Dataset V3 build
- Candidate V2 / model training
- Broker / real-money
- Fake dividend or credit values
- LLM extraction of amounts/dates
