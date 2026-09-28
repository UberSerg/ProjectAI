# Multi-Portfolio V2

Status: **current product model** (supersedes Personal Portfolio V1 singleton `/primary`).

## What it is

A USER can create many independent portfolios (Основной, Дивидендный, ОФЗ, …).
Each portfolio has its own cash, holdings, cost basis, journal, NAV, P&L, analytics,
and Daily Decision.

Selecting a portfolio in the UI is the source of truth for Dashboard and analysis.

## Lifecycle

| State | Meaning |
|-------|---------|
| `DRAFT` | Setup: free cash/position edits; no journal yet |
| `ACTIVE` | Accounting started: journal-driven; direct edits blocked |

Actions:

- **Начать учёт** — DRAFT → ACTIVE (opening snapshot → journal)
- **Очистить** — DRAFT only: cash 0, positions removed
- **Сбросить** — ACTIVE → empty DRAFT (destructive, this portfolio only)
- **Удалить** — hard delete this portfolio only

## Not in scope

- Shadow / Candidate / research portfolios (separate domains)
- IAM / multi-tenancy
- Full bond BUY/SELL trading accounting (holdings + dirty mark OK; new bond trades may stay blocked)
- TWR/XIRR performance %

## Bond opening cost

For DRAFT bond positions ask for optional **total RUB spent** (`cost_basis_total_rub`),
never MOEX clean % as RUB.

- Known total → per-unit RUB basis stored; P&L available when marks exist
- Unknown → market value OK; position P&L and portfolio investment P&L = null

## API (breaking)

Removed product `/personal-portfolios/primary` and `/manual-portfolios/primary`.

Collection:

- `GET/POST /personal-portfolios`
- `GET/PATCH/DELETE /personal-portfolios/{id}`
- draft setup under `/personal-portfolios/{id}/draft/...`
- `POST .../activate`, `POST .../reset`
- operations, analysis, cashflows, daily-decision, compare, rebalance — all `{id}`-scoped

## Migration

Revision `20260928_0025` wipes disposable Manual/Personal user book rows and
starts with an empty collection. Market / Shadow / Candidate / Dataset data untouched.

VERSION remains `1.0.0` until an explicit release iteration.
