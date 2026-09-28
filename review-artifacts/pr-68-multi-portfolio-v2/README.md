# Multi-Portfolio V2 — review artifacts (PR #68 final corrective pass)

**Branch:** `feature/multi-portfolio-v2-manager`  
**Base:** `630245288c261b43452dc4f8c8eb4d4db355f4c0`  
**VERSION:** `1.0.0` (no release/tag)

Screenshots captured against the local Docker `projectai` stack (bind-mounted worktree).
Market candles / instruments / Shadow unchanged; test portfolios created during E2E.

## Screenshots

| # | File | Scene |
|---|------|-------|
| 01 | `01-zero-portfolios.png` | Zero portfolios onboarding (USER) |
| 02 | `02-create-modal.png` | Create portfolio form on `/portfolio` |
| 03 | `03-switcher-two.png` | Switcher with multiple portfolios |
| 04 | `04-draft-manager.png` | DRAFT manager: cash + positions + actions |
| 05 | `05-add-equity.png` | Equity (SBER) with known basis in DRAFT table |
| 06 | `06-add-bond-unknown.png` | Bond with unknown cost basis in DRAFT |
| 07 | `07-bond-no-fake-pnl.png` | Bond row: market value OK, P&L unavailable |
| 08 | `08-activate-confirm.png` | Activation confirm (unknown basis does not block) |
| 09 | `09-active-history.png` | ACTIVE history with «Начальное состояние» labels |
| 10 | `10-dashboard-a.png` | Dashboard portfolio «Основной» |
| 11 | `11-dashboard-b.png` | Dashboard portfolio «ОФЗ» |
| 12 | `12-reset-confirm.png` | Reset confirmation |
| 13 | `13-delete-confirm.png` | Delete confirmation |
| 14 | `14-owner-diagnostics.png` | OWNER view / reconciliation context |
| 15 | `15-edit-draft-cash.png` | DRAFT «Изменить кэш» modal |
| 16 | `16-edit-remove-draft-position.png` | Bond edit modal: total RUB cost (not MOEX %) |
| 17 | `17-draft-preliminary-analysis.png` | DRAFT preliminary analysis (no activation gate) |
| 18 | `18-all-tabs-smoke.png` | ACTIVE tabs smoke (rebalance panel) |

## Limitations (honest)

- Full bond BUY/SELL accounting may remain blocked after activation.
- TWR/XIRR not introduced.
- No IAM / multi-tenancy.
- Dataset V3 / Candidate / Shadow unchanged by this PR.
