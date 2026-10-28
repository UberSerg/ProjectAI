# Review artifacts — PR #85 (remediation)

## Feature
Shadow Portfolio Reliability V1 — final remediation after independent review.

## Commit
Feature HEAD: `098d4c0153e7a1d6f59881797c1b396a625a0b76`  
Worktree: `E:\!AI\ProjectAI-wt-shadow-reliability` serving `localhost:5173` / `:8000`

## Artifacts

| File | What it shows |
|---|---|
| `01-shadow-ops-backlog-not-false-recovering.png` | Ops: backlog 20, Forward lag 29.09, state STALE/BLOCKED — not false RECOVERING |
| `02-shadow-nav-full-fresh-positive-pnl.png` | Live NAV ~1.05M, positive green P&L, 100% quote coverage (no −751k) |
| `03-portfolio-cash-3-34-rub.png` | Portfolio «1» cash **3,34 ₽** (not 3 340) |
| `04-instruments-lkoh.png` | Instrument page (LKOH) loads; DQ/capabilities scoped to instrument |

## Notes
- `origin/main` baseline after #86: `775237298f615cb32f75da9ca7b9cd8250bbbef2`
- GitHub CI success on exact HEAD (run `40748916498`: backend/frontend/docker)
- Live catch-up **not** fully caught up: last_processed=2026-09-29, Forward watermark lag — see PR report
