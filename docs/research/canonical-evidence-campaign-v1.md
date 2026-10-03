# Canonical Evidence Campaign V1

Research-only. Turns Evidence Engine machinery into a frozen **evidence dossier** on real local data.

This is **not** Candidate promotion, Shadow switch, Daily Decision switch, or Kraken 1.04.

## Why it exists

Dataset V4 and Research Evidence Engine V1 can evaluate. They do not yet answer: what data existed, which paired runs were frozen, what chronological OOS showed, how feature groups differed, whether ranking survived next-open economics, how robust that was, and what prospective observations have matured.

## Primary window

- `date_from` = **2022-04-01** because public-data audit places useful online FNS RAS `known_at` coverage around spring 2022. This is **data availability**, not outcome optimization.
- `date_to` = `latest_mature_20d_as_of` from trading calendar + actual prices + 20-session label maturity. **Not** from IC, model return, or economics.
- If `latest_mature_20d_as_of < 2024-04-01` or the window is too short for expanding OOS: `CAMPAIGN_DATA_INSUFFICIENT`. Do not shorten train requirements to force a result.

Optional `FULL_HISTORY_DIAGNOSTIC` from earliest common V3/V4 sample is coverage-only and must not replace the primary window after seeing outcomes.

## Data snapshot

`ResearchDataSnapshotV1` hashes semantic coverage (instruments, prices, CA, fundamentals, events, TR readiness). Missing ≠ 0. READY/PARTIAL/NOT_READY are availability, not alpha.

## Paired V3/V4

Same window, `historical_equity_universe_v2`, mechanical `forward_return_20d`. Spec v3/v4, PIT PASS and 0 violations, exact sample/target identity or `FAIR_CONTRACT_FAIL` (campaign STOPS). ACTIVE DatasetSpec stays v1.

## OOS / ablation / uncertainty

Expanding chronological OOS with 20d purge. Frozen CatBoost hypers, no search. Ablation BASE / +FUNDAMENTALS / +EVENTS / V4 FULL, same rows/y, NATIVE_NAN. Paired date bootstrap deltas with CI; **no winner**.

## Economics

**Primary (predeclared):** ranking V4_FULL, long-only top 20% EW fractional, rebalance 20 sessions, EOD → next OPEN, 30 bps/side **assumed**, PRICE_RETURN, dividends excluded, EW eligible-universe benchmark.

**Robustness matrix (predeclared, not a search):** cost 0/10/30/50 × rebalance 10/20/40 × top 10/20/30. Do not rename the best cell as primary.

Preserve next-open, `SKIPPED_BY_BOUNDARY`, `execution_date > decision_date`, `UNRESOLVED_EXIT` → PARTIAL.

## Prospective

PDM and Forward stay separate from historical OOS. Captures ≠ matured outcomes. No combined accuracy.

## Dossier

Immutable under campaign fingerprint. Completeness statuses are not a master score. `OWNER_REVIEW_STATE = EVIDENCE_DOSSIER_COMPLETE` means planned sections ran — **not** promote Candidate.

## No tuning after observation

After real metrics exist, do not change features, hypers, folds, rebalance, quantile, or costs because results look unattractive. Bugs yes; semantic optimization no.

## Production freeze

`PIT_DAILY_CORE_ACTIVE_VERSION = 1`. Candidate V0/V1 Dataset V2. No registry promotion, Shadow, Daily Decision, PDM mutation, broker execution.

## Workflow steps

Celery task `projectai.canonical_evidence_campaign_v1` runs workflow type `CanonicalEvidenceCampaignV1`:

1. DATA_SNAPSHOT
2. SAFE_DATA_REFRESH
3. BUILD_V3
4. BUILD_V4
5. FAIR_PAIR_PROOF
6. OOS_REGRESSION
7. OOS_RANKER
8. ABLATION
9. STABILITY
10. ECONOMICS_PRIMARY
11. ECONOMICS_ROBUSTNESS
12. PROSPECTIVE_SNAPSHOT
13. DOSSIER
14. FINALIZE

`CAMPAIGN_DATA_INSUFFICIENT`, `FAIR_CONTRACT_FAIL`, and PIT failure block historical OOS/economics. Prospective snapshot and dossier still run.

## API

Registered **before** `/{experiment_id}`:

- `GET /api/v1/research/evidence/campaigns`
- `GET /api/v1/research/evidence/campaigns/{fingerprint}`
- `POST /api/v1/research/evidence/campaigns/canonical-v1` body `{campaign_version, exact_rerun?}` only
- `GET /api/v1/research/evidence/campaigns/{fingerprint}/dossier`

Launch does not accept date/universe/instrument fields. `persist_registry` stays false.
