# Kraken Current State

Mutable handoff snapshot. Update after each merged stage / EOD micro-release.

Stable how-to: `docs/development/KRAKEN_OPERATING_PROTOCOL.md`.
Zero-memory entry: root `AGENTS.md`.

---

## As of

**03.10.2026**

## Latest completed product micro-release

**Kraken 1.03 — 30.09.2026**

(Preceded by **Kraken 1.02 — 29.09.2026**, **Kraken 1.01 — 28.09.2026**; technical first release **Kraken V1.0 / 1.0.0 — 27.09.2026**.)

Investor-visible history: `frontend/src/version/manifest.ts` → `/about`.

## Technical VERSION

`1.0.0` (repository `VERSION` file). Unchanged by product micro-releases 1.01 / 1.02 / 1.03 and by Dataset V4 research merge.

## Baseline main at this state snapshot

```text
BASELINE_MAIN=9b40854ffead508fd2fe4a98d6b3425a0eea4b25
```

This is `origin/main` after the ordinary merge of **PR #75** (Dataset V4 Research Foundation V1).

If current `origin/main` differs, inspect newer merged PRs before continuing.

## Recently completed milestones

| PR | Topic |
|----|--------|
| #69 | Dataset V3 research evaluation + Daily Decision V2 |
| #70 | Personal + Shadow Realism V3 (fees, sell economics, Decision Journal) |
| #71 | Frontend cumulative micro-release history through Kraken 1.02 |
| #72 | Kraken operating protocol and zero-memory handoff |
| #73 | Personal Decision Memory V1 / prospective outcome tracking |
| #74 | Kraken 1.03 EOD product micro-release |
| #75 | Dataset V4 Research Foundation V1 (research-only PIT fund/event enrichment) |

## Current major semantics (in main)

- Personal Decision Memory (explicit immutable capture in Memory DB)
- Displayed-decision fingerprint (capture binds to shown Daily Decision)
- 5 / 20 / 60 trading-session PRICE_RETURN outcomes (dividends not included)
- User-confirmed PersonalOperation links (POSSIBLE_MATCH is not causality)
- Honest quote / session provenance (PREVIOUS_CLOSE → prior trading session)
- Personal current-price coverage (operational mark → honest EOD fallback)
- BrokerAccount / FeeProfile / FeeEngine (versioned; unknown ≠ 0%)
- Shadow Realism V3 (REVIEW ≠ auto-SELL; ROTATE only after economics)
- Shadow Decision Journal
- Daily Decision V2 (Personal portfolio + lots + fees awareness)
- Operating protocol / AGENTS zero-memory bootstrap
- Dataset V3 research-only (`historical_equity_universe_v2`, mechanical price-return)
- Dataset V4 research-only (`historical_equity_universe_v2`, same mechanical labels, PIT fund/event X)
- Production Candidate V0/V1 pinned to Dataset V2; `PIT_DAILY_CORE_ACTIVE_VERSION = 1`

## Active milestone

**NONE** — next bounded milestone to be chosen by Owner.

Do **not** auto-start Dataset V5, Candidate V2, broker execution, UX redesign, or a product micro-release.

## Explicitly not started / out of scope until Owner asks

- Broker real execution / real-money autonomy
- Dataset V5 / production Candidate V2
- New ML production promotion of research candidates
- Causal attribution / win-rate marketing / aggregate «Kraken accuracy %»
- Auto-learning from Decision Memory outcomes
- Shadow mutation / Candidate promotion from Memory evidence
- Universe-wide Total Return labels

## Known operational lesson

`localhost:5173` may still serve a **stale Docker-mounted worktree**.
Before UI acceptance: identify container/process, mount path, branch, HEAD.
After a stage merges, prefer pointing frontend runtime back at current `main`.

## How a new AI should resume

1. `git fetch origin` and read this file for the recorded `BASELINE_MAIN` snapshot SHA.
2. Compare `origin/main` to that SHA; if they differ, inspect newer merged PRs before continuing.
3. Inspect open PRs on GitHub — do not treat a closed/merged PR as still active.
4. If local UI matters, verify the runtime worktree serving port 5173.
5. Ask for / read the **current bounded task** — do not infer unfinished work from the roadmap alone.
6. Read `AGENTS.md` → operating protocol → `AI_WORKFLOW.md` → core rules → domain docs for that task only.
