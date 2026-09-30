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

## Latest baseline main

```text
BASELINE_MAIN=8010793cd8f57d35af39204ff28be8f15830f34f
```

This is the merge commit of PR #71 onto `main`
(`Merge pull request #71 from UberSerg/feature/frontend-release-1.02`).

Final reviewed PR #71 HEAD (ancestor of baseline):

```text
041b85b24a9213542eca719c1a30e756fe8f1f02
```

CI for that HEAD (green attempt 2):

https://github.com/UberSerg/ProjectAI/actions/runs/36676741674

## Recently completed milestones

| PR | Topic |
|----|--------|
| #69 | Dataset V3 research evaluation + Daily Decision V2 |
| #70 | Personal + Shadow Realism V3 (fees, sell economics, Decision Journal) |
| #71 | Frontend cumulative micro-release history through Kraken 1.02 (+ 1.01 metadata fix) |

## Current major semantics (in main)

- Personal current-price coverage (operational mark → honest EOD fallback)
- BrokerAccount / FeeProfile / FeeEngine (versioned; unknown ≠ 0%)
- Shadow Realism V3 (REVIEW ≠ auto-SELL; ROTATE only after economics)
- Shadow Decision Journal
- Daily Decision V2 (Personal portfolio + lots + fees awareness)

## Next planned major milestone

**Personal Decision Memory / prospective outcome tracking**

Not started. Do not begin unless the Owner/curator issues an explicit bounded task.

## Explicitly not started

- Broker real execution / real-money autonomy
- Dataset V4
- New ML production promotion of research candidates
- Personal Decision Memory implementation

## Known operational lesson

`localhost:5173` may still serve a **stale Docker-mounted worktree**.
Before UI acceptance: identify container/process, mount path, branch, HEAD.
After a stage merges, prefer pointing frontend runtime back at current `main`.

## How a new AI should resume

1. `git fetch origin` and read this file for `BASELINE_MAIN`.
2. Confirm `origin/main` still matches (or note newer merges).
3. Inspect open PRs on GitHub.
4. If local UI matters, verify the runtime worktree serving port 5173.
5. Ask for / read the **current bounded task** — do not infer unfinished work from the roadmap alone.
6. Read `AGENTS.md` → operating protocol → `AI_WORKFLOW.md` → core rules → domain docs for that task only.
