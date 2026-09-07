# ADR 0007: Separate EOD decision from intraday execution

Status: accepted.

## Context

Shadow Portfolio V0 creates PENDING orders after EOD Forward decisions and fills them at the next session OPEN. The fill path originally waited for a daily bar in `market.candles`. In live operation that left portfolios in `WAITING_FOR_FUTURE_MARKET_OPEN` until the EOD history ingest landed — even when the official OPEN was already observable on MOEX ISS marketdata.

Intraday quotes must not contaminate durable RAW history or the PIT training/prediction stack.

## Decision

1. Keep **EOD decisioning** on durable `market.candles` + existing Dataset/Prediction/Shadow advance.
2. Add an **opt-in Intraday Market Layer** that fetches board marketdata into **Redis only**.
3. Add **SHADOW_NEXT_SESSION_OPEN_V1** to fill PENDING Shadow orders from quote OPEN (never LAST), with provenance in `ShadowFill.metadata`.
4. Keep candle-based `_fill_pending_orders` as the historical/backfill path.
5. Prediction / Dataset modules must not depend on `IntradayMarketPort`.

## Consequences

- Live open fills no longer require the daily candle row to exist.
- Operators enable the path via `INTRADAY_MARKET_ENABLED` (default false).
- Late polls are allowed only when the order pre-dates session open; `delayed_observation` is recorded.
- UI can show live marks and pending reason codes without writing intraday NAV every refresh.
- Look-ahead risk for training remains unchanged: intraday quotes are execution/UI only.
