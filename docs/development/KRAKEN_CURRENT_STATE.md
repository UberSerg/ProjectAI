# Kraken Current State

Mutable handoff snapshot. Update after each merged stage / EOD micro-release.

Stable how-to: `docs/development/KRAKEN_OPERATING_PROTOCOL.md`.
Zero-memory entry: root `AGENTS.md`.

---

## As of

**04.10.2026**

## Latest completed product micro-release

**Kraken 1.04 — 04.10.2026**

## Technical VERSION

`1.0.0` (repository `VERSION` file). Unchanged by Kraken 1.04.

Product release ≠ technical VERSION ≠ git tag. No GitHub Release for 1.04.

## Baseline main at this state snapshot

```text
BASELINE_MAIN=8cf75a70f8b1565c2568769c23e06b1f83d61054
```

Ordinary merge of **PR #77** Canonical Evidence Campaign V1. Reviewed feature HEAD `00d946ead5ecc7a1155afcabb69f65aec8ed9e5a`.

This EOD release PR records the product checkpoint; it must not change research semantics.

## Recently completed milestones

| PR | Topic |
|----|--------|
| #75 | Dataset V4 Research Foundation V1 |
| #76 | Research Evidence Engine V1 |
| #77 | Canonical Evidence Campaign V1 |

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

- Dataset V3/V4 research-only (`historical_equity_universe_v2`, mechanical PRICE_RETURN)
- Research Evidence Engine V1 (OOS, ablation, next-open economics, prospective read-model, OWNER UI)
- Canonical Evidence Campaign V1 complete; immutable dossiers
- Production Candidate V0/V1 pinned to Dataset V2; `PIT_DAILY_CORE_ACTIVE_VERSION = 1`

## Next product direction (notes only — do not implement here)

**Kraken Intelligence Stack V1** — not Dataset V5 for its own sake.

Candidate areas when Owner asks:

- Intraday / 1h market structure
- Richer fundamental analysis
- RSS/news/event ingestion
- LLM structured information extraction
- Knowledge/rule engine from investment literature
- Independent Technical / Fundamental / Event / Macro / ML models
- Ensemble / investment committee

## Active milestone

None started. Do **not** begin Intelligence Stack V1, Dataset V5, or Kraken 1.05 unless the Owner explicitly tasks it.

## Explicitly not started / out of scope until Owner asks

- Kraken Intelligence Stack V1 implementation
- Broker real execution / real-money autonomy
- Dataset V5 / production Candidate V2
- New ML production promotion
- Aggregate «Kraken accuracy %»
- Universe-wide Total Return labels
- Kraken 1.05

## How a new AI should resume

1. `git fetch origin` and read this file for `BASELINE_MAIN`.
2. Compare `origin/main`; inspect newer merged PRs.
3. Open PRs are not merged until Owner says so.
4. Read `AGENTS.md` → protocol → `AI_WORKFLOW.md` → current task only.
