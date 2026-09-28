# Multi-Portfolio V2 — review artifacts

**Branch:** eature/multi-portfolio-v2-manager  
**Base:** 630245288c261b43452dc4f8c8eb4d4db355f4c0  
**VERSION:** 1.0.0 (no release/tag)

## Screenshots

Screenshots are captured against the local Docker projectai stack (bind-mounted worktree).
Test data created during E2E is marked / cleaned; market candles and instruments are production-dev DB data (not wiped).

| # | File | Scene |
|---|------|-------|
| 01 | 01-zero-portfolios.png | Onboarding empty state |
| 02 | 02-create-modal.png | Create portfolio form on /portfolio |
| 03 | 03-switcher-two.png | Switcher with two portfolios |
| 04 | 04-draft-manager.png | DRAFT portfolio manager |
| 05 | 05-add-equity.png | Add equity position |
| 06 | 06-add-bond-unknown.png | Bond with optional total RUB cost |
| 07 | 07-bond-no-fake-pnl.png | Bond row without fake P&L |
| 08 | 08-activate-confirm.png | Activate confirmation |
| 09 | 09-active-history.png | ACTIVE + History tab |
| 10 | 10-dashboard-a.png | Dashboard portfolio A |
| 11 | 11-dashboard-b.png | Dashboard portfolio B |
| 12 | 12-reset-confirm.png | Reset confirmation copy |
| 13 | 13-delete-confirm.png | Delete confirmation |
| 14 | 14-owner-diagnostics.png | OWNER reconciliation / diagnostics |

> PNG files are added in the same directory when browser capture completes.

## Limitations (honest)

- Full bond BUY/SELL accounting may remain blocked after activation.
- TWR/XIRR not introduced.
- No IAM / multi-tenancy.
- Dataset V3 / Candidate / Shadow unchanged by this PR.

