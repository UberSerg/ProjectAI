# Kraken Current State

Mutable handoff snapshot. Update after each merged stage / EOD micro-release.

Stable how-to: `docs/development/KRAKEN_OPERATING_PROTOCOL.md`.
Zero-memory entry: root `AGENTS.md`.

---

## As of

**03.10.2026**

## Latest completed product micro-release

**Kraken 1.03 — 30.09.2026**

## Technical VERSION

`1.0.0` (repository `VERSION` file). Unchanged by Dataset V4, Research Evidence Engine V1, and Canonical Evidence Campaign V1 (research branches are not product releases).

## Baseline main at this state snapshot

```text
BASELINE_MAIN=dfc4db718808fd940bd577bcf85d1afc7b41b053
```

Ordinary merge of **PR #76** Research Evidence Engine V1. Reviewed HEAD `7cc01c897f221cfa6bce910b1b90e5b54aca82b0` is a merge parent / ancestor.

## Recently completed milestones

| PR | Topic |
|----|--------|
| #75 | Dataset V4 Research Foundation V1 |
| #76 | Research Evidence Engine V1 |

## Current major semantics (in main)

- Dataset V3/V4 research-only (`historical_equity_universe_v2`, mechanical PRICE_RETURN)
- Research Evidence Engine V1 (OOS, ablation, next-open economics, prospective read-model, OWNER UI)
- Production Candidate V0/V1 pinned to Dataset V2; `PIT_DAILY_CORE_ACTIVE_VERSION = 1`

## Active milestone

**Canonical Evidence Campaign V1**

- branch: `feature/canonical-evidence-campaign-v1`
- status: **OPEN / NOT MERGED**
- worktree: `E:\!AI\ProjectAI-wt-canonical-evidence-campaign-v1`

RESEARCH ONLY. No Candidate V2, no Dataset V5, no Shadow/Daily Decision/PDM mutation, no broker execution, no Kraken 1.04.

## Explicitly not started / out of scope until Owner asks

- Broker real execution / real-money autonomy
- Dataset V5 / production Candidate V2
- New ML production promotion
- Aggregate «Kraken accuracy %»
- Universe-wide Total Return labels
- Kraken 1.04

## How a new AI should resume

1. `git fetch origin` and read this file for `BASELINE_MAIN`.
2. Compare `origin/main`; inspect newer merged PRs.
3. Open PRs are not merged until Owner says so.
4. Read `AGENTS.md` → protocol → `AI_WORKFLOW.md` → current task only.
