# KRAKEN UX Sprint Board — Operation Human Interface

**Kickoff:** 2026-10-29  
**Main baseline:** `d211da0943518eaeea11dd7739902c60538cca6f`  
**Orchestrator:** Agent 00 (Cursor)  
**Merge policy:** no auto-merge; Owner approval required per UX PR (prior #85/#91 approval is not blanket).

## Wave status

| Wave | Status | Notes |
|---|---|---|
| 0 Audit / Baseline | **IN_PROGRESS** | Docs PR [#97](https://github.com/UberSerg/ProjectAI/pull/97); browser baselines → Agent 09 |
| 1 Foundations | **IN_PROGRESS** | Agent 01 PR [#98](https://github.com/UberSerg/ProjectAI/pull/98) READY_FOR_REVIEW; Agent 02 Journal V4 running |
| 2 Vertical UX | PLANNED | After token contract stable |
| 3 Integration | PLANNED | Orchestrator only |
| 4 Polish | PLANNED | Mobile/a11y/copy |

## File ownership (hard)

| Agent | Branch | Worktree | Exclusive files |
|---|---|---|---|
| 00 | `ux/audit-product-map` | `E:\!AI\ProjectAI-wt-ux-audit` | `docs/ui/*` (orchestration docs), master-context updates |
| 01 | `ux/design-system-v2` | `E:\!AI\ProjectAI-wt-ux-design-system` | `styles.css`, `design-system.css`, `styles/kraken-dark.css`, `components/Ui.tsx` |
| 02 | `ux/decision-journal-v4` | `E:\!AI\ProjectAI-wt-ux-decision-journal` | `DecisionJournalPanel*`, journal helpers/CSS/tests |
| 03 | `ux/shadow-experience` | `E:\!AI\ProjectAI-wt-ux-shadow` | `ShadowPage.tsx`, shadow `components.tsx`, CatchUpStatusCard* |
| 04 | `ux/personal-portfolio-experience` | `E:\!AI\ProjectAI-wt-ux-portfolio` | `MyPortfolioPage.tsx`, `features/personalPortfolio/*` |
| 05 | `ux/dashboard-navigation` | `E:\!AI\ProjectAI-wt-ux-dashboard` | `DashboardPage.tsx`, `layout/*`, `utils/labels.ts` |
| 06 | `ux/market-intelligence` | *(create when started)* | market/instruments/bonds/intelligence/quotes |
| 07 | `ux/research-simulator` | *(create when started)* | research/simulator/calibration |
| 08 | `ux/system-operations` | *(create when started)* | System/Workflows |
| 09 | `ux/visual-qa` | *(create when started)* | e2e/visual reports only |

**One file → one owner.** Cross-file needs → orchestrator ticket.

## Board

| ID | Pri | Task | Owner | Branch | Deps | State | Done when |
|---|---|---|---|---|---|---|---|
| A0-1 | P0 | Screen passports + issue matrix | 00 | audit | — | DONE (docs) | Merged docs PR |
| A0-2 | P0 | IA + glossary + ownership | 00 | audit | — | DONE (docs) | Merged docs PR |
| A0-3 | P0 | Sprint board + kickoff context | 00 | audit | — | DONE | Context updated |
| A1-1 | P0 | Token contract + cascade plan | 01 | design-system | A0 | **READY_FOR_OWNER_REVIEW** PR [#98](https://github.com/UberSerg/ProjectAI/pull/98) `ade6b27` | Doc + tokens in CSS |
| A1-2 | P0 | Primitives: Money/Status/Empty/Accordion | 01 | design-system | A1-1 | **READY_FOR_OWNER_REVIEW** (same PR #98) | Light+dark desktop/mobile |
| A2-1 | P0 | Journal V4 closed card | 02 | decision-journal | Prefer Ui from #98 | **IN_PROGRESS** | Screenshots + tests |
| A2-2 | P0 | Expand A/B/C/D + reason mapping | 02 | decision-journal | A2-1 | QUEUED | No fabricated why |
| A2-3 | P0 | Stale request fence + a11y | 02 | decision-journal | A2-1 | QUEUED | Abort/stale tests |
| A5-1 | P1 | Dashboard hierarchy + USER nav | 05 | dashboard | A1 | QUEUED | Investor-first hero |
| A3-1 | P1 | Shadow NOW structure | 03 | shadow | A1 | QUEUED | No false recovery |
| A4-1 | P1 | Personal portfolio cabinet | 04 | portfolio | A1 | QUEUED | No PR B mix |
| A6-1 | P1 | Instrument card hierarchy | 06 | market | A1 | PLANNED | — |
| A7-1 | P2 | Research outcome-first | 07 | research | A1 | PLANNED | — |
| A8-1 | P2 | System blockers-first | 08 | system | A1 | PLANNED | — |
| A9-1 | P0 | Before screenshots matrix | 09 | visual-qa | A0 | QUEUED | 1440/1024/768/390/320 |
| A9-2 | P1 | After + a11y report | 09 | visual-qa | Wave2 | PLANNED | QA report |

## Integration order (Wave 3 draft)

1. Docs audit PR (00)  
2. Design system PR (01)  
3. Decision Journal V4 PR (02) — showcase  
4. Dashboard/nav (05)  
5. Shadow (03)  
6. Personal portfolio (04)  
7. Market / Research / System  
8. QA report  

## Safety checklist (every PR)

- [ ] No finance formula / ledger / Shadow history rewrite  
- [ ] No network/Docker/auth changes  
- [ ] Missing≠0; Partial≠Full; LIVE≠Replay; Decision≠Order≠Fill  
- [ ] Exact-HEAD CI green  
- [ ] Desktop+mobile screenshots  
- [ ] Owner review before merge  

## Handoff protocol

Each agent ends with: changed files, tests, screenshots path, blockers, next agent needs, exact SHA.
