# MOEX Fixed Income — cashflow / bondization

Primary schedule endpoint:

`/iss/securities/{secid}/bondization.json`

| Block | Role |
|-------|------|
| coupons | Coupon event dates and observed amounts/rates |
| amortizations | Principal reductions; `data_source=maturity` is redemption |
| offers | Put/call-like offer events — never auto-exercise |

Audit artifact: `.tmp/fixed-income-cashflow-v1/moex-bond-cashflow-audit.json`

Board securities remain the source for clean price, NKD (`ACCRUEDINT`), YIELD, DURATION,
LOTSIZE, FACEUNIT.
