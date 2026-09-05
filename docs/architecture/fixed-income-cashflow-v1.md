# Fixed Income Cashflow Coverage V1

## Source

Official cashflow schedule:

`GET https://iss.moex.com/iss/securities/{secid}/bondization.json`

Blocks:

- `coupons` — coupondate, value, valueprc, facevalue, faceunit, …
- `amortizations` — amortdate, value, valueprc, data_source (`maturity` / `amortization`)
- `offers` — offerdate, price, offertype, …

Board path `.../markets/bonds/securities/{secid}/bondization.json` does **not** return
bondization (returns securities/marketdata). Separate `/coupons.json` aliases fall back to
description.

## known_at

Bondization is **CURRENT_STATE_ONLY**: event dates exist, publication timestamps and
historical schedule revisions do not. Suitable for live as-of-now accounting; **not** for
reconstructing what was knowable at historical decision time `t`.

`cashflow_date` = economic event date. `known_at` at ingest = observation/as_of date with
quality recorded in `raw_fields.known_at_quality`.

## SUPPORTED V1

RUB face + nominal + lot + maturity + fixed observed coupon schedule (all remaining coupons
have amounts) + no complex amortization + no future offer + market price present.
No guessed cashflows.

Corporate `SUPPORTED` means accounting support only; `credit_quality=UNKNOWN` ⇒
`real_portfolio_eligible=false`.

## Historical total return

`BOND_HISTORICAL_TOTAL_RETURN = NOT_READY` until a PIT-capable cashflow archive exists.
