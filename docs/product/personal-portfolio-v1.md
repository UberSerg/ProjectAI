# Personal Portfolio V1

## Decision

Extend **Manual Portfolio** (`portfolio.manual_*`) with an authoritative **operation journal**.
Do **not** reuse Shadow / Simulator ledgers for real money.

- Projected balances: `manual_portfolios.cash_rub`, `manual_positions`
- Source of truth: `portfolio.personal_operations` (append-only; corrections via SUPERSEDED/CANCELLED)
- Accounting: **weighted-average cost**
- Commission: embedded on BUY/SELL **or** separate `COMMISSION` — never both for the same fee
- Money math: `Decimal` / `NUMERIC` only
- Isolated E2E/tests: `is_test=true` portfolios (never the owner's real book)

## External capital vs investment P&L

`investment_pnl = NAV - (contributed - withdrawn)`

Deposits increase contributed and NAV together → investment P&L stays 0 when markets do nothing.
