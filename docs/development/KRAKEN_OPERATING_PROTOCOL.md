# Kraken Operating Protocol

Stable project operating manual for ProjectAI / Kraken.

This document explains **how we develop**. For **what is true today**, see
`docs/development/KRAKEN_CURRENT_STATE.md`. For a zero-memory bootstrap, see
root `AGENTS.md`. Implementation details: `docs/development/AI_WORKFLOW.md`.
Architecture invariants: `.cursor/rules/00-project-core.mdc` and
`docs/architecture/`.

---

## 1. Roles

| Role | Responsibility |
|------|----------------|
| **Owner** | Goals, product decisions, priorities, explicit merge/EOD authorization |
| **ChatGPT / curator** | Architecture, decomposition, Cursor mega-prompts, independent GitHub review, invariant checks, READY TO MERGE judgment, next bounded milestone |
| **Cursor** | Implementation, local repo research, tests, commit/push/PR, structured Final Report |
| **GitHub** | Authoritative history of code, PRs, CI |

**Cursor Final Report is an executor claim.** It does **not** replace independent
GitHub verification (exact HEAD, base, commits, diff, CI on that SHA, invariants,
acceptance evidence).

---

## 2. Normal development cycle

1. Curator forms a **bounded** mega-prompt.
2. Cursor implements on a clean feature branch / worktree from current `main`.
3. Cursor opens a PR. A new functional PR is usually **not** merged by Cursor.
4. Cursor delivers a Final Report.
5. Curator independently verifies:
   - exact PR HEAD;
   - base;
   - commits;
   - diff / relevant files;
   - CI for that exact SHA;
   - architectural invariants;
   - acceptance evidence.
6. Blockers → narrow remediation prompt (same PR).
7. When the PR is **READY TO MERGE**, the next Cursor prompt may:
   - merge the reviewed PR with an **ordinary merge commit**;
   - then create a **new** clean branch/worktree for the next stage.
8. One roadmap stage → one PR. Do not mix two stages in one PR.

---

## 3. Merge policy

- Default for large Kraken milestones: **ordinary merge commit**.
- Avoid squash/rebase unless Owner/curator explicitly requires it (history of stages and remediations must stay readable).
- Do **not** merge the current functional PR without explicit authorization.
- After merge: `git fetch origin` and record the exact `origin/main` SHA as baseline when closing a stage.

---

## 4. Proportionate verification

Match test cost to risk.

| Task type | Expected bar |
|-----------|--------------|
| Backend / data / financial semantics | Full applicable quality bar (tests, lint, migrations head, Docker health when runtime changed) |
| Small frontend text / docs / process | Do **not** auto-run Docker/backend/migrations/full infra; check syntax/links/paths; run only if the task touches those surfaces |

Never claim “everything works” unless the relevant check was actually executed.
Never spend an hour of acceptance for a two-line text change.

---

## 5. Local worktrees and Docker (operational lesson)

Multiple git worktrees are normal.

Docker frontend may keep mounting an **old** worktree even after new code exists
on another branch. Therefore:

> “frontend is fixed” ≠ “localhost shows the fix”.

Before UI acceptance, identify:

1. which process/container listens on port `5173`;
2. which host path / worktree is mounted;
3. branch;
4. HEAD.

Prefer recreating **only** the frontend service when switching worktrees.
Do not rebuild the entire stack without need.

After a stage merges, return runtime mounts to current `main` when practical so the
next day does not start on a stale feature worktree.

---

## 6. Architectural invariants (short list)

Do not restate the whole roadmap. Hard rules:

### Core

- Instrument Master ≠ Research Universe.
- Prediction ≠ Policy ≠ Risk ≠ Execution.
- Current data ≠ historical PIT evidence.
- `period_end` ≠ `known_at`.
- Missing ≠ zero; Unknown beats fabricated values.
- Cash is a first-class position.
- LLM is not a numerical financial truth source.
- Real-money execution OFF until prospective economics are proven.
- Free/public data sources unless Owner changes policy.
- No HFT / tick ML / Kafka / ClickHouse / new infra without proven need.

### Execution semantics

Baseline investment execution semantics:

`EOD decision → next eligible market session official OPEN execution → subsequent intraday monitoring / valuation.`

Changing execution/policy semantics requires a new experiment/version — never a
silent rewrite of old history. Never backdate Shadow fills.

Canonical detail: `.cursor/rules/00-project-core.mdc`,
`docs/architecture/future-intelligence-roadmap.md`.

---

## 7. Personal Portfolio truth

Chain of truth:

Operations → holdings → cash → cost basis → realized/unrealized P&L → valuation
→ Daily Decision → (later) Personal Decision Memory.

Hard rules:

- Market price known + cost basis unknown → market value / NAV may be known;
  **P&L must be UNKNOWN/NULL**.
- Missing cost basis must **not** block NAV.
- Never use purchase price as current market fallback.
- Operational current mark order:
  1. current/live operational mark;
  2. latest honest local EOD close;
  3. unavailable.
- Current instrument mapping may support CURRENT valuation, but
  `valid_from=NULL` is **not** historical PIT evidence.

---

## 8. Broker / fees

Conceptual model: `BrokerAccount → FeeProfile → FeeRules`.

- FeeProfile is **versioned**.
- Unknown fee ≠ 0%.
- Personal operation fee provenance: `MANUAL > PROFILE_ESTIMATE > NONE`.
- Manual commission wins; commission counted once.
- Daily Decision BUY: trade notional + broker fee ≤ available cash.
- Do not mix broker fee, exchange/system fee, and slippage.
- Built-in Sber mirror may be used only for the FeeProfile version it actually
  represents (currently product mirror for exact builtin v1 rules only).
  Never impersonate v2/v999 with v1 rules.

---

## 9. Shadow Realism (post-#70)

- Old prospective Shadow experiments remain immutable.
- **V3:** exit rank/drop out of band = **REVIEW** trigger, not automatic SELL.
- Held position actions: HOLD / REVIEW_HOLD / DATA_HOLD / ROTATE /
  EXIT_TO_CASH / RISK_REDUCE / RISK_EXIT when independently justified.
- ROTATE only if measurable expected advantage covers:
  sell fee + buy fee + sell slippage + buy slippage + configured margin/edge.
- Ranking score is not automatically expected return.
- Missing economics/data → not SELL; prefer DATA_HOLD unless independent risk exit.
- REVIEW_HOLD / DATA_HOLD ⇒ `sell_allowed = false`; lot planner must not secretly sell.
- No phantom funding: retained capital cannot fund a replacement buy.
- Fee semantics must agree across sell gate → planner → execution → fills/accounting.

---

## 10. Shadow Journal vs Personal Decision Memory

| Concern | Role |
|---------|------|
| **Shadow Decision Journal** | Structured evidence of simulated/prospective Shadow experiment decisions |
| **Personal Decision Memory** | Advice shown for the real Personal portfolio + later actual user action + prospective outcome observations |

Do **not** share one table/domain for both.

Decision evidence ≠ hidden chain-of-thought. Persist structured facts, reason
codes, provenance — not internal reasoning transcripts.

---

## 11. Next milestone rule

On the Kraken 1.02 baseline, the next planned **major** milestone is:

**Personal Decision Memory / Outcome Tracking**

Concept: Daily Decision → immutable recommendation snapshot → actual user action
(if any) → observations at 5/20/60 trading sessions → descriptive evaluation.

Important:

- recommendation ≠ execution;
- possible temporal match ≠ causal proof;
- missing action ≠ HOLD;
- missing outcome ≠ 0;
- no historical backfill pretending old advice existed;
- no look-ahead; observations are prospective.

This protocol document does **not** authorize starting that implementation.

---

## 12. User experience principles

- Russian, investor-first.
- Investment product, not a developer/admin dashboard by default.
- OWNER technical details may exist; USER view must explain investor meaning.
- Do not convert unknown into fake certainty.
- Help/tooltips are welcome for hard terms.
- Do not break wide layout with a global max-width clamp.

---

## 13. Real data safety

Prefer TEST portfolio / fixtures / isolated experiments for acceptance.

- Do not mutate real USER holdings for checks.
- Read-only inspection of real data is allowed if state is unchanged.
- Never delete shared market history / Shadow evidence for test cleanup.

---

## 14. End-of-Day micro-release protocol

When Owner says something like “last prompt today / closing the day / prepare the summary”,
that is the **EOD trigger**.

### 14.1 Product micro-release ≠ GitHub Release

Examples: `Kraken 1.01` (28.09.2026), `Kraken 1.02` (29.09.2026).

These are investor-visible development history entries in
`frontend/src/version/manifest.ts`.

They are **not**:

- technical `VERSION`;
- SemVer package bumps;
- git tags;
- GitHub Releases;

unless Owner explicitly requests a technical release.

### 14.2 End-of-day steps

1. Determine next product micro-version.
2. Summarize only **actually completed** changes.
3. Write concise Russian release notes (version, date, changes, limits).
4. **Append** a new entry at the top of frontend release history.
5. Never overwrite or delete older entries.
6. Verify current version on top; previous versions still readable; dates/text preserved.
7. Confirm `/about` shows the new history.
8. Verify which branch/worktree/container serves `localhost:5173`.
9. After merge, return frontend runtime to current `main` if it was on a feature worktree.
10. Update `KRAKEN_CURRENT_STATE.md` (micro-release, baseline SHA, completed/next milestones).

### 14.3 When EOD is finished

A micro-release is **not** durable merely because text sits in an uncommitted worktree
(that was the 1.01 failure mode).

Prefer:

committed → pushed → reviewed → **merged into main** → `/about` shows it.

If merge has not happened yet, state explicitly:

`EOD MICRO-RELEASE PENDING MERGE`

### 14.4 History is append-only

New version on top. Old version / date / text / provenance must not disappear.
Product micro-releases do not receive invented git tags.

### 14.5 Technical VERSION

Do not change repository `VERSION`, create a tag, or publish a GitHub Release
without a separate explicit Owner task.

---

## 15. Daily management summary (chat-only)

At EOD, curator also gives Owner chat estimates:

- MD (man-days) equivalent;
- replacement-cost range;
- product-value uplift estimate in ₽ (central + rationale);
- readiness % before → after (+ percentage points).

These are **estimates**, not bookkeeping. By default they stay in Owner↔curator chat —
**not** frontend, **not** public release notes, **not** product financial truth —
unless Owner asks otherwise.

---

## 16. Source priority on contradiction

1. Explicit current Owner task.
2. Current GitHub `main` + reviewed current PR state.
3. `AGENTS.md` / `KRAKEN_CURRENT_STATE.md` / alwaysApply Cursor rules.
4. Current architecture docs.
5. Historical / legacy docs.
6. Old chat reports.

**Exception:** current code cannot silently cancel an explicit architectural
invariant. If conflict is found — stop and escalate.

---

## 17. Docs-only quality bar

For protocol/docs PRs:

- Do **not** run Docker / backend pytest / full frontend / migrations / expensive acceptance.
- Check markdown paths/links, file existence, exact baseline SHAs, clean bounded diff.
- Run `.mdc` validation only if an existing command already covers it.
