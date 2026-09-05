# Credit Quality V0

## Why high yield can mean risk

A bond with a high coupon/yield is not automatically a defensive asset. Yield may
compensate for default risk, weak issuer quality, or illiquidity.

## Accounting ≠ investment

| Layer | Question |
|---|---|
| Accounting quality | Can we compute price, coupons, cashflows? |
| Investment quality | Is it suitable for a defensive sleeve? |

Example: Accounting SUPPORTED + Credit UNKNOWN → Investment RESEARCH_ONLY.

## What Kraken does

- Stores credit assessments with explicit status: UNKNOWN / AVAILABLE / NOT_RATED / CONFLICT / STALE
- Never invents SAFE / GUARANTEED / LOW_RISK
- Never invents `credit_score = 87`
- Does not bypass paid rating feeds (`READY_REQUIRES_ACCESS`)
- Treats agency scales as non-interchangeable without mapping

## Bonds ≠ deposit

OFZ / corporates are not cash deposits. Unknown rating is a warning, not an error that
hides the instrument — and not a green light.
