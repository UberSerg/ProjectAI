# Review artifacts — PR #63

## Feature
Personal Portfolio V1 + lean image-only release runtime (development toward future V1.1; no version bump).

## Commit
`50929bb` on `feature/personal-portfolio-v1`

## Artifacts

| File | What it shows |
|---|---|
| `01-personal-portfolio-empty.png` | Live empty primary portfolio onboarding (Основной портфель) |
| `02-personal-portfolio-summary.png` | Summary cards: NAV, contributed, cash, securities, investment P&L |
| `03-add-deposit.png` | Add operation modal — Пополнение |
| `04-add-buy.png` | Add operation modal — Покупка with instrument/lots/price |
| `05-position-pnl.png` | Positions table with average/current price and P&L |
| `06-operation-history.png` | Recent journal (deposit / buy / commission / +30k / sell) |
| `07-owner-reconciliation.png` | OWNER diagnostics: Reconciliation OK + operation IDs |
| `08-dashboard-personal-binding.png` | Dashboard hero bound to personal portfolio valuation |

## Notes
- Screenshots 02–07 use the isolated `is_test=true` E2E portfolio state (mocked in browser for review) so the owner's future real book is not polluted.
- Contribution 130 000 ₽ vs investment P&L −38.8 ₽ proves deposits are not counted as profit.
- Dark V1.0 theme preserved; USER/OWNER toggle visible.
- Release runtime proof was run separately (image-only, then DEV bind mounts restored).