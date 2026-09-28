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
| `DO_NOTHING` | New money stays undeployed |
| `HOLD_CASH` | Hypothetically park as portfolio cash |
| `TARGET_UNDERWEIGHTS` | Deploy toward candidate underweights without selling |
| `KRAKEN_ALLOCATION` | Sleeve plan from current research decision when trustworthy |
| `FIXED_INCOME_ALTERNATIVE` | Honest FI sleeve alternative when data exists (no fake OFZ ticker) |

New-cash plans never invent forced sales. Overweights do not receive extra capital when underweights exist.

## Lots / bonds / CBR

- Equity lots reuse existing LOTSIZE resolution; unknown lot → `lots = null` (never fake `1`)
- Bond suggestions marked `ADVISORY_ONLY_BOND_TRADE`
- CBR hurdle shown as cash/risk-free **context**, not guaranteed deposit return

## Confidence

`data_confidence.status`: `SUFFICIENT` | `PARTIAL` | `LOW` — qualitative completeness, not a probability.

## Isolation

- Portfolio-scoped
- Dataset V3 research evaluation does **not** drive USER Decision V2 (`dataset_v3_drives_decision: false`)
- DRAFT remains supported and labeled preliminary

## Decision Memory

Persisting recommendation → outcome learning is **out of scope** for this iteration (requires curator-approved schema).
