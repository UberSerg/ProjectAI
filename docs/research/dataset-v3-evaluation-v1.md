# Dataset V3 evaluation (research)

## Scope

Measurable research evaluation of `pit_daily_core` **v3** vs **v2**.

This document does **not** authorize production activation.

## Contracts

| Spec | Universe | Labels | Active? |
|---|---|---|---|
| v1 | `current_active_instruments` | legacy | **ACTIVE** |
| v2 | `current_active_instruments` | mechanical price-return | inactive |
| v3 | `historical_equity_universe_v2` | mechanical price-return (same X pins as v2) | inactive / research |

- `PIT_DAILY_CORE_ACTIVE_VERSION = 1`
- `PIT_DAILY_CORE_RESEARCH_VERSION = 3` (alias only; does not activate)
- V3 is **not** total-return; `fundamentals_in_features = false`
- Successful V3 DatasetRuns freeze the semantic contract — do not mutate in-place

## Fair V2↔V3 compare

Same: `date_from`, `date_to`, feature schema, technical/relation pins, mechanical labels.  
Only intended difference: universe policy.

Library: `compare_v2_v3_builds`  
API (OWNER/research): `POST /api/v1/learning/datasets/compare-v2-v3`

Artifact fields include run ids/hashes, sample counts, year coverage, inactive representation, PIT, trainable horizons, missingness, unique V2/V3 samples, factual interpretation (**no** «V3 wins»).

## Research quality grade (CORE)

Additive `coverage_summary.research_quality` on V3 builds:

- `READY_FOR_RESEARCH` | `PARTIAL` | `NOT_READY`
- Explicit thresholds in `dataset_config.py`
- Never means production-ready / Candidate / Shadow switch

## Historical universe

Fail-hard if historical universe cannot resolve — **no** silent fallback to `current_active_instruments`.

TD-008 remains OPEN: delisted MOEX coverage incomplete; quality stays PARTIAL.

## Model comparison (experimental OOS)

Candidate V0/V1 remain pinned to Dataset V2. Production registry upserts are forbidden on the research path.

Research-only tooling (does **not** touch Candidate pins / ACTIVE DatasetSpec):

- Coverage compare CLI: `python -m app.modules.learning.cli_compare`
- Explicit v2|v3 loader: `app.modules.prediction.application.research_dataset_loader`
- Chronological OOS runner: `app.modules.prediction.application.research_runner`
  (`EXPERIMENTAL_V3_RESEARCH`; identical CatBoost hyperparameters; `persist_registry=False` only)

Side-by-side OOS metrics are factual; they do **not** authorize Candidate promote/rollback or ACTIVE switch.
