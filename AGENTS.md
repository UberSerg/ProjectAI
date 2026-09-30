# AGENTS — zero-memory bootstrap for ProjectAI / Kraken

If you are a new AI/agent with no chat memory about this repository:

**Do not start changing code.**

First read the documents below and verify the **current GitHub state**.

## Mandatory reading order

1. `AGENTS.md` (this file)
2. `docs/development/KRAKEN_CURRENT_STATE.md` — mutable handoff snapshot
3. `docs/development/KRAKEN_OPERATING_PROTOCOL.md` — stable operating manual
4. `docs/development/AI_WORKFLOW.md` — implementation / review workflow
5. `.cursor/rules/00-project-core.mdc` — always-on architecture invariants
6. Relevant architecture / domain docs for the **current bounded task only**

## Source of truth

| Claim | Authority |
|-------|-----------|
| What is on main | `origin/main` on GitHub |
| What a PR contains | exact PR HEAD SHA + diff + CI for that SHA |
| What Cursor “reported” | **not** proof — independent GitHub verification required |
| What localhost shows | not proof until the serving worktree/container/HEAD is identified |

GitHub is the durable project memory. Chat history is ephemeral.

## Before any non-trivial work

1. `git fetch origin`
2. Read `KRAKEN_CURRENT_STATE.md` for baseline SHA and next milestone
3. Inspect open PRs / CI on GitHub
4. Confirm local branch / HEAD / worktree
5. If UI acceptance matters: identify what serves `localhost:5173` (process, Docker mount, branch, HEAD)
6. Take the **explicit current Owner/curator task** as scope — do not invent the next roadmap stage

## Hard behavioural rules

- Do **not** automatically start the next milestone after finishing a task.
- Do **not** merge a functional PR unless the Owner/curator explicitly authorizes merge.
- Prefer ordinary **merge commits** for large Kraken milestones (readable history).
- Proportionate verification: small docs/frontend-text tasks must not trigger Docker/backend/migration marathons.
- Stale docs must be reconciled against code + GitHub; if an architectural invariant conflicts with code, **stop and ask**.

## Product vs technical versioning

- Investor-visible product micro-releases live in `frontend/src/version/manifest.ts`.
- Product micro-version ≠ technical `VERSION`, SemVer tag, or GitHub Release unless Owner explicitly requests that.
- Repository technical `VERSION` is separate; read its **current** value from `KRAKEN_CURRENT_STATE.md` / root `VERSION`.

## Next planned major milestone

Read the current planned milestone from `KRAKEN_CURRENT_STATE.md`.
Do **not** start it unless explicitly tasked.
