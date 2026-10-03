# Dataset V4 Research Foundation V1

Research-only additive DatasetSpec: `pit_daily_core` **version 4**.

This document does **not** authorize production activation, Candidate promotion,
Shadow/Personal switch, or a product micro-release.

Status at writing: **OPEN / NOT MERGED** on `feature/dataset-v4-research-foundation-v1`.

Technical `VERSION` remains `1.0.0`. Latest completed product release remains **Kraken 1.03**.

## 1. Why V4 exists

V3 already gives a survivorship-aware historical universe and mechanical price-return labels.
It does **not** put PIT fundamentals or corporate/event evidence into `X(t)`.

V4 exists so research can ask a single isolated question:

> Did richer PIT-safe fundamental/event features change research signal,
> holding universe, labels, model family, and OOS cut fixed?

V4 is a more honest research object than V3 only in **evidence**: lineage, missingness,
and PIT diagnostics. It is not “better alpha” and is not a production Candidate.

## 2. Exact semantic difference V3 → V4

| | V3 | V4 |
|---|---|---|
| Universe | `historical_equity_universe_v2` | same |
| Primary labels | mechanical price-return (horizons 1/5/10/20) | same contract (`LABEL_SPEC_V2`) |
| Price basis | mechanical adjusted (SPLIT / REVERSE_SPLIT) | same |
| Base X | Analytics + Technical + Relations (`FEATURE_MANIFEST_V1`) | same base |
| Fundamentals in X | false | true — frozen same-report **ratios** |
| Events in X | false | true — frozen `event_*` pack |
| Missingness | n/a for fund/event | native missing / NaN; never convenience 0 |
| Lineage / coverage | universe + PIT | plus `v4_enrichment` + return-truth diagnostics |
| Production | research-only | research-only |
| `PIT_DAILY_CORE_ACTIVE_VERSION` | 1 | 1 (unchanged) |

Intended X delta: `FEATURE_MANIFEST_V4` = V3 names **plus** the frozen V4 packs in
`dataset_config.py`.

## 3. What did NOT change

- Dataset V1 / V2 / V3 definitions (immutable historical contracts)
- Active DatasetSpec (`pit_daily_core` v1)
- Candidate V0 / V1 pins (Dataset V2)
- Shadow portfolio, Daily Decision, Personal Decision Memory
- FeeEngine, broker execution, production model registry
- Primary label family (not Total Return)

## 4. Why labels remain price-return

Fair V3↔V4 comparison requires one experimental axis: **features**.
Changing labels at the same time would confound “richer X” with “different Y”.

Mechanical corporate-action normalization remains SPLIT / REVERSE_SPLIT only.
Dividends are not in the primary label.

## 5. Why Total Return is still not claimed

Dividend PIT coverage is incomplete. Empty `dividend_events` is **NOT_READY**, not
“zero cashflow”. V4 must not set `total_return=true`, must not fill missing dividends
as 0, and must not promote partial IR-only dividends into universe-wide TR labels.

`coverage_summary.return_truth` reports this honestly (`RESEARCH_DIAGNOSTIC_ONLY`).

## 6. Fundamental / event feature contract

**Choice: same-report ratios, not raw size.** Monetary facts are not cross-sectionally
comparable without unit/currency identity. Raw `fund_revenue` etc. are **not** V4 X
columns. EBITDA stays out (registry `AMBIGUOUS`).

Fundamental pack:

- `fund_days_since_latest_report`
- `fund_report_age_days`
- `fund_has_recent_report`
- `fund_net_margin` (NET_INCOME / REVENUE)
- `fund_operating_margin` (OPERATING_INCOME / REVENUE)
- `fund_debt_to_equity` (TOTAL_DEBT / TOTAL_EQUITY)
- `fund_cash_to_assets` (CASH_AND_EQUIVALENTS / TOTAL_ASSETS)
- `fund_equity_to_assets` (TOTAL_EQUITY / TOTAL_ASSETS)
- `fund_operating_cash_flow_to_revenue` (OPERATING_CASH_FLOW / REVENUE)

A ratio is computed only when both facts are `NORMALIZED`, same report, compatible
currency/unit_scale, denominator is a genuine non-zero. No epsilon.

Event pack:

- `event_days_since_last_split`
- `event_split_events_365d`
- `event_days_since_last_dividend_disclosure`
- `event_last_disclosed_dividend_per_share`
- `event_has_known_upcoming_dividend`
- `event_days_to_next_dividend_record_date`

If the store has **no dividend disclosures** for the instrument, upcoming-dividend is
**missing**, not `0`. “Unknown coverage” ≠ “we know there is no dividend”.

Industrial RAS / bank semantics: unsupported features stay missing with an explicit
reason. No ticker-name issuer typing.

## 7. PIT / known_at rules

- `period_end` ≠ `known_at`; `record_date` / `ex_date` ≠ `known_at`
- Feature knowledge date must be `<=` sample `as_of`
- A future economic date is a valid feature only if its **disclosure** `known_at <= T`
- Restatements are versioned: a later `known_at` must not leak into earlier samples
- Validation fails the DatasetRun on V4 `feature_known_at` lookahead

## 8. Missingness policy

Missing stays missing. No zero-fill, no median impute, no forward-fill of unknown
information. Research CatBoost path uses `missing_feature_policy = NATIVE_NAN`.
Coverage reports missing counts/shares without converting missing to 0.

## 9. Historical universe policy

Same as V3: `historical_equity_universe_v2`. Fail hard if resolution fails — no silent
fallback to currently active instruments. `instrument_ids` cannot bypass eligibility.
Currently inactive names remain historically representable inside `eligible_from`…
`eligible_to`. Instrument Master ≠ research universe.

## 10. Research quality grade

V4-only, never production:

| Grade | Meaning |
|---|---|
| `READY_FOR_RESEARCH` | Enough evidence to run **controlled research** |
| `PARTIAL` | Usable with listed caveats (low coverage, CURRENT_ONLY share, …) |
| `NOT_READY` | PIT violation, universe failure, zero enrichment, malformed contract, … |

Constants: `RESEARCH_V4_PARTIAL_MIN_ENRICHMENT_PCT`, `RESEARCH_V4_PARTIAL_CURRENT_ONLY_PCT`
in `dataset_config.py`. Grade is a list of reasons, not a single score.

`READY_FOR_RESEARCH` does **not** mean Candidate should use V4.

Issuer identity bases remain visible: `DATED_WINDOW` / `CURRENT_ONLY` / `UNMAPPED`.
CURRENT_ONLY is an assumption, never disguised as a dated window. Valid_from/to are
never manufactured.

## 11. OOS experiment contract

- Research versions allowed: **2, 3, 4** (not 1)
- TRAIN: `as_of_date < cut` **and** `target_date_20d` exists **and** `< cut`
- No randomized split; no temporal overlap
- V3 vs V4: same window, universe, primary target, OOS cut, CatBoost family,
  hyperparameters, seed; different X manifest by design
- Labels: `EXPERIMENTAL_V4_RESEARCH` / `V3_V4_FEATURE_ENRICHMENT_RESEARCH`
- `persist_registry=False` only — no production registry writes
- Insufficient samples → `status=insufficient_samples`, not fake metrics

Library: `run_experimental_v2_v3_oos(..., dataset_spec_version=4)` and
`compare_experimental_model_v3_v4`.

## 12. Production isolation

- `PIT_DAILY_CORE_ACTIVE_VERSION = 1`
- Candidate V0/V1 remain Dataset V2
- Compare endpoints/CLI must not call `seed_dataset_specs()` (that helper activates v1)
- Fair compare isolation: `active_dataset_spec.before == after`

Paths:

- Build: existing dataset build workflow with `dataset_spec_version=4`
- Compare: `POST /api/v1/learning/datasets/compare-v3-v4`
- CLI: `python -m app.modules.learning.cli_compare --pair v3-v4 ...`

OWNER/research only. No public USER diagnostic endpoints. No Research Lab UI in this
milestone (backend correctness first; UI would be a later low-risk add).

## 13. Known limitations

- Dividend PIT coverage incomplete → Total Return not primary
- Bank / FI industrial RAS semantics unsupported for several metrics
- Historical delisted coverage still PARTIAL (TD-008)
- CURRENT_ONLY issuer mappings are weaker than DATED_WINDOW
- FNS GIR BO industrial RAS ≠ banks
- No production promotion path in this milestone

## 14. What would be required before any future production promotion

Not claimed here. A later, explicit Owner task would still need at least:

- Frozen V4 (or later) contract after successful DatasetRuns
- Walk-forward / Candidate→Champion process
- Honest TR decision (or explicit keep-price-return)
- Shadow then Signal then human-confirmed execution — never a jump from one research OOS
- No automatic registry / Shadow / Daily Decision switch from a single compare artifact

## Hardening (PR #75 remediation)

- V3↔V4 model OOS requires identical sample keys and identical 20d target semantics (`FAIR_CONTRACT_FAIL` otherwise).
- Explicit `Issuer.metadata.fns.support_status = NOT_SUPPORTED_BY_FNS_RAS_V1` blocks all industrial V4 fundamental features.
- `return_truth` is provider-aware: empty store / unaccepted provider → `NOT_READY`; bounded `universe_wide=false` → at most `PARTIAL`.
- Duplicate `NORMALIZED` facts must agree or the metric is missing; overlapping mappings to different issuers are `AMBIGUOUS`.

## Implementation notes

- Enrichment: `app.modules.learning.application.v4_enrichment` — batched SQL preload
  (O(1) queries vs sample count), in-memory PIT timelines
- Builder coverage: `coverage_summary.v4`, `return_truth`, `research_quality`
- Loader: `feature_names_for_spec_version(version)` — V4 missing keys → NaN
