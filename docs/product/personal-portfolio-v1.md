# Personal Portfolio V1

> **Superseded by Multi-Portfolio V2** — see `docs/product/multi-portfolio-v2.md`.
> Singleton `/primary` and auto-create «Основной портфель» are retired.
> This document remains as historical design notes for the journal/projection model
> that V2 reuses under portfolio-id scoping.

## Decision

Extend **Manual Portfolio** (`portfolio.manual_*`) with an authoritative **operation journal**.
Do **not** reuse Shadow / Simulator ledgers for real money.

- Projected balances: `manual_portfolios.cash_rub`, `manual_positions`
- Source of truth: `portfolio.personal_operations` (append-only; corrections via SUPERSEDED/CANCELLED)
- Accounting: **weighted-average cost**
- Commission: embedded on BUY/SELL **or** separate `COMMISSION` — never both for the same fee
- Money math: `Decimal` / `NUMERIC` only
- Isolated E2E/tests: `is_test=true` portfolios (never the owner's real book)

## Source of truth / downstream analytics

```text
journal (personal_operations)
  → projection (manual_portfolios / manual_positions)
  → PersonalPortfolioSnapshot (load_personal_snapshot)
  → analytics (allocation, concentration, risk, credit, compare, rebalance, cashflows)
  → Dashboard / My Portfolio UI
```

| Layer | Role |
|---|---|
| Journal | Authoritative financial history (ACTIVE) |
| Projection | Derived current cash/positions for efficient reads |
| `load_personal_snapshot` | **Sole application read boundary** for user-facing Personal analytics |
| Candidate / Shadow / Research | Separate books — not mixed into «Мой портфель» |

After `journal_state=ACTIVE`, legacy Manual write APIs remain blocked. Downstream must not treat a raw `ManualPortfolio` load as an independent source of truth; always go through the Personal snapshot (marks, cost-basis usability, valuation completeness).

Bond cost basis remains unavailable until dedicated bond accounting exists — analytics must not invent unrealized P&L from legacy `% of nominal` average prices.

## External capital vs investment P&L

`investment_pnl = NAV - (contributed - withdrawn)`

Deposits increase contributed and NAV together → investment P&L stays 0 when markets do nothing.
