# Shadow Portfolio Realism V2

## Purpose

Turn Shadow from an execution proof-of-concept into a **realistic virtual investment portfolio**:

- integer exchange lots (MOEX LOTSIZE);
- cash-safe order planning with fees;
- position cost basis / realized & unrealized P&L;
- durable EOD NAV snapshots;
- autonomous EOD → next-session readiness;
- intraday OPEN fill + LAST marks (unchanged from V1).

## Architectural split (unchanged)

```text
EOD: candles → analytics → Forward → Policy target → lot-aware Order Plan
Intraday: MOEX OPEN/LAST (Redis) → fill eligible orders → live marks
```

Intraday quotes never enter Prediction / Feature / `market.candles`.

## Experiment decision

**New experiment group:** `SHADOW_PORTFOLIO_REALISM_V2`

| | V1 `SHADOW_FORWARD_V0` | V2 Realism |
|--|--|--|
| Positions | May be fractional | Integer lots only |
| LOTSIZE | Ignored | Required (no silent `1`) |
| History | Frozen / immutable | Fresh capital, prospective |
| Prediction/Policy | Candidate V0 + hysteresis | **Same** (execution realism only) |

Do **not** rewrite V1 fills. Comparability with Historical Simulator (still fractional by default) is explicitly limited until Simulator Realism V2.

## Lot plan

Ideal Policy weights → executable integer lots:

1. Reserve strategic cash (if any) + fee budget.
2. Sells first (integer lots) → proceeds available.
3. Buys by deterministic priority (rank / target weight / ticker).
4. Skip with explicit reasons (`UNKNOWN_LOT_SIZE`, `INSUFFICIENT_CASH_FOR_ONE_LOT`, …).
5. Leftover cash after rounding is valid (not forced equity).

Shared primitive with Candidate V1: `cash + price + lot_size + target → lots/units` (Decimal / `TransactionCostProfile`).

## Accounting

Position JSON (V2): `quantity`, `lots`, `lot_size`, `avg_entry`, `cost_basis`, `realized_pnl`.

- Live mark = fresh LAST (fallback stale close).
- EOD NAV = durable `ShadowNavDaily` after complete daily closes (not intraday LAST).

## Daily automation

1. After session close: readiness gate (data completeness, not naive clock).
2. Daily Research Cycle once when ready (idempotent Forward + Shadow advance).
3. Status `READY_FOR_NEXT_SESSION` or blocker codes.
4. Morning intraday poll fills on official OPEN.
5. Daytime LAST marks ~5 minutes.

Missed days / missed readiness → operational incident, **no** retrospective same-open fill for orders created after open.

## Settings

See `.env.example`:

- `DAILY_RESEARCH_CYCLE_*` — scheduled full EOD cycle
- `EOD_READINESS_RETRY_ENABLED` / `EOD_READINESS_RETRY_MINUTES` — lightweight completeness poll that triggers the cycle **once** when ready (does not re-run the full cycle every few minutes)
- `INTRADAY_MARKET_*` — OPEN fills + LAST marks

## Init V2 (does not touch V1)

```bash
# CLI
python -m app.modules.shadow.cli init --group realism-v2

# API
POST /api/v1/shadow/init?group=realism-v2
```

Daily Research Cycle advances both `SHADOW_FORWARD_V0` and `SHADOW_PORTFOLIO_REALISM_V2`.

Ops: `GET /api/v1/shadow/daily-operations` (alias `/operations/status`).
