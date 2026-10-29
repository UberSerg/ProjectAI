# KRAKEN UX/UI Swarm — Code-Based Audit and Execution Contract

Date: 2026-10-29. Owner-selected UX direction: **Decision Journal Variant 4** (expandable cards with traceable WHY). This is a source-code audit, **not** verified end-to-end visual inspection of every route. Browser baseline/reproduction is Wave 0 work for Cursor.

## Verified starting point

- Main at audit: `c54a6f1252815c3c5dece8a626a9a2f4642259d6`, after owner-approved PR [#85](https://github.com/UberSerg/ProjectAI/pull/85) (merge `a1c165b5d6378cff8e7cfae86a2aaf79199e4a1a`) and PR [#91](https://github.com/UberSerg/ProjectAI/pull/91) (merge `512628b2798bc81f91a480769e08adfcdbe6169d`). Newer HEAD must be verified before engineering work.
- #85 exact-head CI 40863675688 on `4a271975f0953097480da5ba68171e35aa18bc8a` succeeded; #91 exact-head CI 40864314012 on `c56fd53e0af24e5f382484aff5d921b1552c02f7` succeeded.
- The redundant integration PR [#95](https://github.com/UberSerg/ProjectAI/pull/95) was closed without merge after #91 merged concurrently.
- Full live multi-day Shadow catch-up remains an independently unverified operational step; it is outside this UX scope.

## Concrete source findings and scope proposals

| Priority | Area / exact source | Code-based finding | UX acceptance target |
|---|---|---|---|
| P0 UX | `features/shadow/DecisionJournalPanel.tsx` | Day `<details>` already exists; closed summary is dense date/risk/NAV/cash/DD/count chips, with no clearly styled WHY action, no prominent per-ticker decisions; candidates and fills are raw wide tables | Owner Variant 4: human-first day cards, ticker/action chips, explicit `Детали решения`, separate actual orders/fills and source-based explanations |
| P0 UX / P1 reliability | same file | `getShadowJournal` uses AbortController, but the then-path does not check `signal.aborted`; checking `String(portfolioId)` against a string captured from the same render does not fence late responses from old filters or portfolio | Ignore outdated requests for same portfolio/different filter and across portfolio changes; add delayed Promise tests |
| P0 finance display | `pages/ShadowPage.tsx`, `features/shadow/components.tsx` | Overview uses `liveNav ?? p.nav ?? p.cash` and `live_market_value ?? ... ?? 0` presentation fallbacks; absent live marks may be visually conflated with historical or zero values | Read valuation completeness/freshness and distinguish absent vs real zero; do not change financial formulas or invent NAV |
| P1 | `main.tsx`, `styles.css`, `design-system.css`, `styles/kraken-dark.css` | Three ordered CSS layers with overlapping themes/tokens; light `Inter` and dark `Manrope` styles both exist | One documented token contract and design-system owner; no uncontrolled competing global CSS edits |
| P1 | `pages/MyPortfolioPage.tsx` | ~1300-line page with 7 tabs; native `window.prompt`/double `window.confirm` for rename/delete; history primarily technical table; tablist buttons need semantic keyboard audit | Human portfolio hierarchy, accessible tab pattern and explicit safe dialogs; financial operation behavior untouched |
| P1 | `pages/DashboardPage.tsx` | ~724-line dashboard already investor-first with hero NAV, P&L, cash, securities, but content and quality/status compete for attention | Primary portfolio answer / decision / next action, quieter health and diagnostics, clear full/partial/stale states |
| P1 | `layout/navConfig.ts`, `layout/AppShell.tsx`, `App.tsx` | USER has 4 top navigation destinations, OWNER many research/market items, multiple expert routes/aliases and placeholder routes | A clear investor-first journey with progressive OWNER disclosure; preserve deep links and URL route semantics |
| P1 | `pages/ShadowPage.tsx` | ~1220 lines spanning live states, recovery, arms, decisions, execution, order tables and journal | Separate NOW / DECISION / EXECUTION / RISK / TECHNICAL without false recovery claims |
| P1 | `pages/InstrumentsPage.tsx`, `pages/InstrumentPage.tsx`, `features/quotes/*` | Dense filters, data quality and market charts; investigate loading/races and mobile table interaction in browser | Price + as-of + instrument + reason above diagnostic fields; dedicated mobile chart and filter states |
| P2 | `pages/ResearchLabPage.tsx`, Research Evidence / Simulator pages | Many configuration inputs, expandable details and dense tables even when the user wants outcome first | Context, result, trust level, limitations, comparison, then advanced params |
| P2 | `pages/SystemPage.tsx`, `pages/WorkflowsPage.tsx` | Diagnostics, raw technical codes and operational statuses compete for visible hierarchy | Owner-only operations cockpit with blockers and next action first, raw trace/details last |
| P1 QA | `frontend/e2e/investor-journey.spec.ts`, `package.json` | Playwright E2E exists but covers a narrow decision→capture→refresh slice; browser E2E is not in main CI (per product doc) | Deterministic DEMO-only browser acceptance and visual baselines for 1440 / 1024 / 768 / 390 / 320 px |

These are grounded observations/recommendations; not all are independently reproduced defects. Wave 0 must confirm real browser behavior and classify reproduced findings separately.

## Multia­gent file ownership

- **00 Orchestrator/Audit:** `docs/ui/*`, routing of tasks, PR integration only.
- **01 Design System:** `frontend/src/styles.css`, `frontend/src/design-system.css`, `frontend/src/styles/kraken-dark.css`, `frontend/src/components/Ui.tsx`, global tokens.
- **02 Decision Journal V4:** `frontend/src/features/shadow/DecisionJournalPanel*` and scoped CSS/tests only.
- **03 Shadow Experience:** `frontend/src/pages/ShadowPage.tsx`, `frontend/src/features/shadow/components.tsx`, CatchUpStatusCard and tests; excludes DecisionJournalPanel.
- **04 Personal Portfolio:** `frontend/src/pages/MyPortfolioPage.tsx`, `frontend/src/features/personalPortfolio/*` and scoped CSS/tests; no financial operation algorithm changes.
- **05 Dashboard and Navigation:** `frontend/src/pages/DashboardPage.tsx`, `frontend/src/layout/*`, shared `utils/labels.ts`.
- **06 Market and Intelligence:** market, instrument, bonds, fundamentals, intelligence and quotes pages/features.
- **07 Research and Simulator:** research, calibration and simulator pages/features.
- **08 System/Operations:** system and workflows pages/features.
- **09 UX QA:** isolated E2E/visual tests, accessibility reports, no parallel production edits.

No two agents may edit the same file without orchestrator approval. Non-design agents should scope feature CSS, not alter global styles. Do not overwrite Cursor's existing dirty worktrees. Use one feature branch/worktree/PR per agent.

## UX invariants

1. Human answer → explanation → evidence → expert diagnostics.
2. The accordion explains existing **Decision → Order → Fill** data; no generated/fabricated rationale.
3. `NAV ≠ P&L ≠ drawdown`, `Missing ≠ 0`, `PARTIAL ≠ FULL`, `RECORDED LIVE ≠ COUNTERFACTUAL_REPLAY`.
4. Mark existing legacy anomalies only from evidence/quality metadata; do not rewrite historical records.
5. USER is simplified; OWNER retains technical drill-down. Presentation role is not an authentication boundary.
6. No networking, ports, firewall, auth, external history, historical financial journals or finance-engine edits.
7. PR B Personal Operations Integrity and PR C Frontend Data Loading are separate planned scopes; report relevant defects rather than silently mixing them into broad UX PRs.

## Waves and quality gate

- **Wave 0**: Audit, real baseline screenshots, route/state/viewport matrix, exact files and agent ownership.
- **Wave 1**: Design tokens and base components; Journal V4 architecture; dashboard/navigation with explicit non-overlap.
- **Wave 2**: Parallel feature-specific UI PRs after token contract; each supplies before/after screenshots and regression tests.
- **Wave 3**: One integrator merges only owner-approved, reviewed PRs, resolves conflicts, reruns exact-head frontend/backend/Docker CI and browser acceptance.
- **Wave 4**: Mobile, keyboard/focus, accessible contrast, degraded states, copy consistency, error recovery, animation polish.

Acceptance: real walkthrough creates/opens portfolio, sees trustworthy NAV, moves to instrument, views a recommendation, opens decision history, distinguishes recorded decision from order/fill, and can understand unavailable data without engineering help. OWNER can trace a Shadow decision and provenance. Browser screenshots must distinguish true backend data from forced/mock overlays.

## Definition of Done / reporting

Each PR: explicit source finding, root cause, owner/worktree, changed paths, user-visible result, tests, exact HEAD/CI, real desktop/mobile screenshots, financial-data limitations, remaining work. After every meaningful milestone update BOTH Current State and Activity Log of `docs/development/CHATGPT_MASTER_CONTEXT.md` using normal GitHub commits. Do not claim completion if context update is pending. Previous approval to merge #85/#91 is not blanket approval for all UX PRs.
