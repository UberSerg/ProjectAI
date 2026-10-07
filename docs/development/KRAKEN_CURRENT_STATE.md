# Kraken Current State

Mutable handoff snapshot. Update after each merged stage / EOD micro-release.

Stable how-to: `docs/development/KRAKEN_OPERATING_PROTOCOL.md`.
Zero-memory entry: root `AGENTS.md`.

---

## As of

**07.10.2026**

## Latest completed product micro-release

**Kraken 1.05 — 07.10.2026**

## Technical VERSION

`1.0.0` (repository `VERSION` file). Unchanged by Kraken 1.05.

Product release ≠ technical VERSION ≠ git tag. No GitHub Release for 1.05.

## Baseline main at this state snapshot

```text
BASELINE_MAIN=58283d8118de2cfd36bd490ad9b3a4ffd9450234
```

Ordinary merge of **PR #79** Kraken Intelligence Stack V1.

| Item | Value |
|------|--------|
| Status | COMPLETE / MERGED |
| Reviewed feature HEAD | `df7ed50bb6235079cd3f147e9d916bb32dab276f` |
| Merge commit | `58283d8118de2cfd36bd490ad9b3a4ffd9450234` |

This EOD release PR records the product checkpoint. It must not change intelligence semantics.

## Recently completed milestones

| PR | Topic |
|----|--------|
| #75 | Dataset V4 Research Foundation V1 |
| #76 | Research Evidence Engine V1 |
| #77 | Canonical Evidence Campaign V1 |
| #79 | Kraken Intelligence Stack V1 — COMPLETE / MERGED |

## Kraken Intelligence Stack V1

Status: **COMPLETE / MERGED** via PR #79.

| Item | Value |
|------|--------|
| Migration | `20261007_0027` |
| Schema | `intelligence` (13 tables) |
| Bounded acceptance as_of | 2026-10-07 |
| Exact-head CI on reviewed HEAD | 1379 passed, 8 skipped, 3 warnings |

Committee states from that acceptance are observations, not proven investment performance.

Production Candidate was not switched. Real broker execution was not enabled.

## Canonical Evidence Campaign V1

Status: **COMPLETE** (in main via PR #77).

| Item | Value |
|------|--------|
| Canonical dossier | `fe5609a2ced6082992d923bc57cf99655d73e2787c119564de42bc48803bf233` |
| Superseded audit dossier | `caf1d5703aae7c2c008015e82cc1086cf68d0fa71f138eb05eb39bec2a25cd75` (`OOS_EVALUATION_BOUNDARY_MISMATCH`) |
| V3 DatasetRun | 655 SUCCESS / PIT PASS / 0 / 42988 samples |
| V4 DatasetRun | 659 SUCCESS / PIT PASS / 0 / 42988 samples |
| Window | 2022-04-01 → 2026-09-01 |
| OOS contract | `evaluation_end_policy=CAMPAIGN_DATE_TO_INCLUSIVE`, `development_end_exclusive=2026-09-02` |

Research conclusion (factual, not a winner claim): current V4 fundamentals/events have **not** demonstrated incremental OOS value over BASE.

Ablation mean rank IC: BASE +0.0138; BASE+FUNDAMENTALS +0.0010; BASE+EVENTS −0.0134; V4_FULL −0.0106.

## Current major semantics (in main)

- Intelligence Stack V1
- real MOEX 60m intraday
- FNS industrial fundamentals
- bank-specific honest unsupported state
- CBR/MOEX news ingestion
- macro/regime
- Knowledge Engine
- independent model outputs
- deterministic Investment Committee
- Risk/Scenario Engine
- Company Intelligence OWNER UI
- IntelligenceRefreshV1
- Intelligence Research V1
- production isolation
- Dataset V3/V4 research-only (`historical_equity_universe_v2`, mechanical PRICE_RETURN)
- Research Evidence Engine V1 and Canonical Evidence Campaign V1 remain complete
- Production Candidate V0/V1 pinned to Dataset V2; `PIT_DAILY_CORE_ACTIVE_VERSION = 1`

## Next product direction (notes only — do not implement here)

Not Dataset V5.

- real LLM provider integration + structured event extraction
- richer Event/News intelligence
- accepted bank-specific fundamental provider
- deeper honest 60m history
- research provenance wiring for CrossSectionalML
- prospective accumulation of news/event evidence
- later evidence evaluation of intelligence feature packs

## Active milestone

None started. Do **not** begin the next intelligence milestone, Dataset V5, or Kraken 1.06 unless the Owner explicitly tasks it.

## Explicitly not started / out of scope until Owner asks

- Next intelligence work: real LLM provider, richer event/news, bank-specific fundamental provider, deeper 60m history, CrossSectionalML provenance, prospective news accumulation, later evidence evaluation of intelligence feature packs
- Broker real execution / real-money autonomy
- Dataset V5 / production Candidate V2
- New ML production promotion
- Aggregate «Kraken accuracy %»
- Universe-wide Total Return labels

## How a new AI should resume

1. `git fetch origin` and read this file for `BASELINE_MAIN`.
2. Compare `origin/main`; inspect newer merged PRs.
3. Open PRs are not merged until Owner says so.
4. Read `AGENTS.md` → protocol → `AI_WORKFLOW.md` → current task only.
