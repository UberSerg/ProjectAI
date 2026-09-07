# Portfolio Cashflow Intelligence V1

## Scope

Gross cashflow projection for Manual Portfolio bond positions.

## Events

| Type | Counted in gross? |
|------|-------------------|
| BOND_COUPON | yes |
| BOND_AMORTIZATION | yes |
| BOND_REDEMPTION | yes |
| OFFER | informational only |

## Horizons

30d / 90d / 12m (365d) from `as_of`.

## Rules

- Units × per-bond amount → gross.
- Same-date REDEMPTION + final AMORTIZATION → keep redemption only (no double-count).
- Analysis enrichment: maturity ladder, gov vs corp counts (issuer concentration remains on analysis tab).

## API / UI

- `GET /api/v1/manual-portfolios/primary/cashflows`
- My Portfolio → tab **Выплаты**

## Limits

- Depends on enriched cashflows (`CURRENT_STATE_ONLY`).
- Pre-tax, pre-commission.
- Not a broker cash forecast; advisory research view.
