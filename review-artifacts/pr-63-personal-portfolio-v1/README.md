# Review artifacts — PR #63

## Feature
Personal Portfolio V1 — **final correctness pass** (explicit legacy cutover).

## Commit
`c9260c338676b0de2d90761704bedec23e9a4e53` on `feature/personal-portfolio-v1`

## Artifacts

| File | What it shows |
|---|---|
| `01-personal-portfolio-empty.png` | Empty onboarding |
| `02-personal-portfolio-summary.png` | Active journal summary |
| `03-add-deposit.png` | Add deposit |
| `04-add-buy.png` | Add buy |
| `05-position-pnl.png` | Positions |
| `06-operation-history.png` | Journal |
| `07-owner-reconciliation.png` | OWNER reconciliation |
| `08-dashboard-personal-binding.png` | Dashboard absolute P&L / «В бумагах» |
| `09-partial-valuation.png` | Partial valuation |
| `10-legacy-cutover.png` | LEGACY_PENDING activation CTA |
| `11-bond-pnl-unavailable.png` | Bond market value with P&L unavailable |

## Notes
- Screenshots use isolated test/mock state — owner real book not polluted.
- Final pass: explicit `activate-journal`, pre-cutover rejection, bond unrealized null, `valuation_as_of` null when mixed/partial, cancel intent idempotency.