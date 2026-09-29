# Daily Personal Decision V2

## Purpose

Answer: «У меня есть новый капитал X ₽. Что Kraken предлагает сделать с ним в контексте выбранного портфеля?»

Decision V2 extends the existing Daily Personal Decision engine. It does **not** create a second engine and does **not** write financial history.

## API

`GET /api/v1/personal-portfolios/{portfolio_id}/daily-decision?new_cash_rub=`

- `new_cash_rub` optional, `Decimal >= 0`, default `0`
- Read-only hypothetical input
- Does **not** create `DEPOSIT`
- Does **not** mutate cash, contributed capital, operations, or projection

Without `new_cash_rub`, V1-style fields remain usable (`engine_version` may still report `"2"`).

## Scenarios

When `new_cash_rub > 0`, response includes `scenario_comparison`:

| id | Meaning |
|---|---|
| `DO_NOTHING` | New money stays **outside** the portfolio (`external_unallocated_rub`; cash share uses current NAV) |
| `HOLD_CASH` | New money enters as hypothetical cash (`nav + new_cash`) |
| `TARGET_UNDERWEIGHTS` | RUB shortfall `max(0, candidate_weight * hypo_nav - current_mv)`; overweights get 0 |
| `KRAKEN_ALLOCATION` | Sleeve targets + candidate underweight shortfalls (not equal chunks of current holdings) |
| `FIXED_INCOME_ALTERNATIVE` | Advisory FI sleeve (`executable_notional = 0`, `ADVISORY_ONLY`) |

New-cash plans never invent forced sales. Overweights do not receive extra capital.

Scenario accounting (except `DO_NOTHING`): `executable_notional + advisory_only + residual_cash = new_cash`.

Stale candidate (`candidate_stale`): `TARGET_UNDERWEIGHTS` is not a precise available plan (`CANDIDATE_STALE`). Live preview is labeled `live_preview` and is not stale merely due to missing snapshot age.

## Lots / bonds / CBR

- Equity lots reuse existing LOTSIZE resolution; unknown lot → `lots = null` (never fake `1`)
- Track `target_rub` vs `executable_estimated_notional_rub` vs lot residual
- Bond suggestions marked `ADVISORY_ONLY_BOND_TRADE` — not counted as deployed
- UI copy: Целевой объём / Можно оценить по лотам / Только ориентир / Остаётся
- CBR hurdle shown as cash/risk-free **context**, not guaranteed deposit return

## Confidence

`data_confidence.status`: `SUFFICIENT` | `PARTIAL` | `LOW` — qualitative completeness, not a probability.

## Isolation

- Portfolio-scoped
- Dataset V3 research evaluation does **not** drive USER Decision V2 (`dataset_v3_drives_decision: false`)
- DRAFT remains supported and labeled preliminary

## Decision Memory

Persisting recommendation → outcome learning is **out of scope** for this iteration (requires curator-approved schema).
