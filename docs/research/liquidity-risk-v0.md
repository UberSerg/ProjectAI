# Liquidity Risk V0

## Liquidity risk

The risk that an instrument is hard to buy or sell quickly at an expected price.

## What Kraken uses

Observed MOEX / candle proxies:

- last trade / snapshot date
- volume when available
- trade count when available

Spread is **not invented** when absent.

## Statuses

GOOD / MEDIUM / LOW / UNKNOWN — documented thresholds, not optimized.

## Guardrails

Reasons: STALE_PRICE, LOW_VOLUME, NO_RECENT_TRADES, UNKNOWN_LIQUIDITY.

LOW liquidity blocks defensive research eligibility; UNKNOWN stays a visible warning.
