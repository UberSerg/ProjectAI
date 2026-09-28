# Dataset V3 readiness gate V1

**Measurement only for Total Return enrichment.** Mechanical Core is a separate contract.

## Dated update (2026-09-27) — Core vs TR enrichment

After `DATASET-V3-CORE-01`, distinguish:

| Track | Meaning | Gate |
|---|---|---|
| **Dataset V3 Core** | `pit_daily_core` v3: `historical_equity_universe_v2` + mechanical price-return labels (`dividend_adjusted=false`, `total_return=false`) | **READY** for explicit research builds; not auto-activated; Candidate V1 stays on V2 |
| **Total Return enrichment** | Universe-wide PIT dividends + TR labels / fundamentals depth | Still **NOT READY** without production dividend PIT feed |
| **Historical universe completeness** | Board/candle evidence coverage | **PARTIAL** — survivorship-aware where evidence exists; delisted market-wide coverage incomplete |

Prior audits (2026-09-08) remain valid for **TR / fundamentals** blockers. They do **not** forbid building mechanical V3 Core.

Do not read this document as “any Dataset V3 is forbidden to build.”

## Gate values (TR enrichment)

| Gate | Meaning |
|---|---|
| `NOT_READY` | Insufficient industrial RAS (or schema missing) |
| `READY_FOR_DATASET_DESIGN` | Industrial RAS present; design discussion allowed |
| `READY_FOR_BUILD` | Would require RAS **and** accepted dividend PIT feed (+ coverage) for **TR enrichment** |

**Hard rule:** fundamentals alone ≠ `READY_FOR_BUILD` (TR).

**Hard rule:** IR-only / bounded issuer XLS dividends do not unlock TR `READY_FOR_BUILD`.

## Evidence (2026-09-08)

- FNS online RAS window ~2021–2025; candidate feature start ≈ **2022-03-01**
- Dividends: e-disclosure spike `PARTIAL_RESEARCH_ONLY` → TR labels blocked
- Banks: `NOT_SUPPORTED_BY_FNS_RAS_V1`
- Identity gaps: ROSN/NVTK/GMKN/PLZL UNMAPPED without authoritative FNS org

## Isolation

- Active DatasetSpec remains `pit_daily_core` v1
- Candidate V1 remains on Dataset V2
- V3 Core builds are explicit research-only
- See also: `docs/research/dataset-v3-evaluation-v1.md` (V2↔V3 fair compare, research_quality grade)

## Brain Foundation V2 note

V3 semantic contract is frozen after successful DatasetRuns. Evaluation tooling must not mutate V3 feature/label/universe semantics; only additive diagnostics and compare artifacts are allowed.
- Candidate V1 remains pinned to Dataset V2
- Shadow / production prediction unchanged by Core seeding
- Dividend safety gate not weakened

## API / CLI

- `GET /api/v1/fundamentals/dataset-v3-gate`
- `python -m app.modules.fundamentals.cli dataset-v3-gate`
- Artifact: `.tmp/public-fundamentals-dividends-foundation-v1/dataset-v3-readiness.json`

Gate payload includes `v3_core` and `total_return_enrichment` sub-objects after 2026-09-27.
