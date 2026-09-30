# Kraken Current State

Mutable handoff snapshot. Update after each merged stage / EOD micro-release.

Stable how-to: `docs/development/KRAKEN_OPERATING_PROTOCOL.md`.
Zero-memory entry: root `AGENTS.md`.

---

## As of

**30.09.2026**

## Latest completed product micro-release

**Kraken 1.02 — 29.09.2026**

(Preceded by **Kraken 1.01 — 28.09.2026**; technical first release **Kraken V1.0 / 1.0.0 — 27.09.2026**.)

Investor-visible history: `frontend/src/version/manifest.ts` → `/about`.

## Technical VERSION

`1.0.0` (repository `VERSION` file). Unchanged by product micro-releases 1.01/1.02.

## Baseline main at this state snapshot

```text
BASELINE_MAIN=fbde57004a5c8b3fde66909736e4faf9044b7e6f
```

This was `origin/main` when this Personal Decision Memory V1 milestone branch was started
(merge of PR #72: Kraken operating protocol / zero-memory handoff).

If current `origin/main` differs, inspect newer merged PRs before continuing.

## Recently completed milestones

| PR | Topic |
|----|--------|
| #69 | Dataset V3 research evaluation + Daily Decision V2 |
| #70 | Personal + Shadow Realism V3 (fees, sell economics, Decision Journal) |
| #71 | Frontend cumulative micro-release history through Kraken 1.02 |
| #72 | Kraken operating protocol and zero-memory handoff |

## Current major semantics (in main)

- Personal current-price coverage (operational mark → honest EOD fallback)
- BrokerAccount / FeeProfile / FeeEngine (versioned; unknown ≠ 0%)
- Shadow Realism V3 (REVIEW ≠ auto-SELL; ROTATE only after economics)
- Shadow Decision Journal
- Daily Decision V2 (Personal portfolio + lots + fees awareness)
- Operating protocol / AGENTS zero-memory bootstrap

## Active milestone

**Personal Decision Memory V1 — prospective outcome tracking**

Status: **PR #73 OPEN / NOT MERGED**
(branch `feature/personal-decision-memory-v1` — **not completed until merged**).

PR: https://github.com/UberSerg/ProjectAI/pull/73

Scope in this branch (Memory DB only, prospective capture):

- Explicit `POST .../decision-memory/capture` (no write-on-GET for daily-decision)
- Immutable `personal_decision_records` / actions / outcomes / operation links
- 5/20/60 **trading-session** PRICE_RETURN outcomes + explicit refresh
- Investor UI: «Зафиксировать решение» + «История решений»
- Retention: Core portfolio reset does **not** CASCADE-delete Memory evidence

Baseline at milestone start:

```text
BASELINE_MAIN=fbde57004a5c8b3fde66909736e4faf9044b7e6f
```
## Explicitly not started / out of scope for this milestone

- Broker real execution / real-money autonomy
- Dataset V4
- New ML production promotion of research candidates
- Causal attribution / win-rate marketing
- Shadow mutation / Candidate promotion
- EOD product micro-release 1.03 (Owner EOD only)

## Known operational lesson

`localhost:5173` may still serve a **stale Docker-mounted worktree**.
Before UI acceptance: identify container/process, mount path, branch, HEAD.
After a stage merges, prefer pointing frontend runtime back at current `main`.

## How a new AI should resume

1. `git fetch origin` and read this file for the recorded `BASELINE_MAIN` snapshot SHA.
2. Compare `origin/main` to that SHA; if they differ, inspect newer merged PRs before continuing.
3. Inspect open PRs on GitHub (this milestone may still be OPEN / NOT MERGED).
4. If local UI matters, verify the runtime worktree serving port 5173.
5. Ask for / read the **current bounded task** — do not infer unfinished work from the roadmap alone.
6. Read `AGENTS.md` → operating protocol → `AI_WORKFLOW.md` → core rules → domain docs for that task only.
