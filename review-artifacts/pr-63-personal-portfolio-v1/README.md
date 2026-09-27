# Review artifacts — PR #63

## Feature
Personal Portfolio V1 + lean release runtime — **corrective financial pass**.

## Commit
`0f0884b8cb315e1008e67b130756775b4c5a507b` on `feature/personal-portfolio-v1`

## Artifacts

| File | What it shows |
|---|---|
| `01-personal-portfolio-empty.png` | Live empty primary onboarding |
| `02-personal-portfolio-summary.png` | Summary: NAV / contributed / cash / investment P&L (absolute) |
| `03-add-deposit.png` | Add operation — deposit |
| `04-add-buy.png` | Add operation — buy form |
| `05-position-pnl.png` | Positions + P&L |
| `06-operation-history.png` | Journal history |
| `07-owner-reconciliation.png` | OWNER Reconciliation OK |
| `08-dashboard-personal-binding.png` | Dashboard: absolute investment result, label «В бумагах», no fake % |
| `09-partial-valuation.png` | Partial valuation: investment P&L unavailable |

## Notes
- Screenshots 02–09 use isolated `is_test` / mocked review state (owner real book not polluted).
- Bond journal trades are blocked (backend + UI); covered by automated tests.
- Corrective fixes: bond dirty valuation, legacy bootstrap, journal write guards, partial P&L null, mixed as-of, idempotency intent.