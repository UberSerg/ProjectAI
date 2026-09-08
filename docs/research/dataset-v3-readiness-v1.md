# Dataset V3 readiness gate V1

**Measurement only.** No `DatasetSpec` is created, pinned, or mutated.

## Gate values

| Gate | Meaning |
|---|---|
| `NOT_READY` | Insufficient industrial RAS (or schema missing) |
| `READY_FOR_DATASET_DESIGN` | Industrial RAS present; design discussion allowed |
| `READY_FOR_BUILD` | Would require RAS **and** accepted dividend PIT feed (+ coverage) |

**Hard rule:** fundamentals alone ≠ `READY_FOR_BUILD`.

## Evidence (2026-09-08)

- FNS online RAS window ~2021–2025; candidate feature start ≈ **2022-03-01**
- Dividends: e-disclosure spike `PARTIAL_RESEARCH_ONLY` → TR labels blocked
- Banks: `NOT_SUPPORTED_BY_FNS_RAS_V1`
- Identity gaps: ROSN/NVTK/GMKN/PLZL UNMAPPED without authoritative FNS org

## Isolation

Dataset V2 (`pit_daily_core` v2 hashes), Prediction, Candidate, Shadow,
`research_fi_v1` (21) remain unchanged by this gate.

## API / CLI

- `GET /api/v1/fundamentals/dataset-v3-gate`
- `python -m app.modules.fundamentals.cli dataset-v3-gate`
- Artifact: `.tmp/public-fundamentals-dividends-foundation-v1/dataset-v3-readiness.json`
