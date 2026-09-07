# Intraday Market Layer & Shadow Open Execution V1

## Purpose

Separate **EOD decision / durable market history** from **intraday observation / shadow open fills**.

V1 unblocks Shadow portfolios stuck in `WAITING_FOR_FUTURE_MARKET_OPEN` when the next session OPEN exists on the exchange but the daily bar has not yet landed in `market.candles`.

## Two paths

### EOD / durable path (unchanged)

```text
MOEX history → market.candles (RAW OHLCV)
  → Dataset / Prediction / Forward Signal (PIT)
  → Shadow advance → PENDING orders (min_execution_date = decision_date + 1)
  → candle-based _fill_pending_orders when daily OPEN bar exists
```

- `market.candles` remains the immutable source of RAW daily OHLCV.
- Historical Simulator and Shadow backfill still use `HistoricalNextOpenAdapter.fill` on candle OPEN.
- Dataset / Prediction / training **must not** import `IntradayMarketPort`.

### Intraday / ephemeral path (V1)

```text
MOEX ISS board marketdata → IntradayQuote
  → Redis keys projectai:intraday:{board}:{secid} (TTL)
  → SHADOW_NEXT_SESSION_OPEN_V1 eligibility
  → fill at official session OPEN (never LAST)
  → ShadowFill.metadata provenance
```

- Quotes are **Redis-ephemeral only**.
- **Never** write intraday quotes into `market.candles`.
- Live NAV from LAST is computed on read for UI; not persisted every refresh.

## Persistence boundary

| Data | Store | Durable? |
|------|-------|----------|
| Daily OHLCV | `market.candles` | Yes |
| Intraday quotes | Redis | No (TTL, default 1200s) |
| Shadow orders / fills | `portfolio.*` | Yes |
| Fill provenance | `ShadowFill.metadata` JSONB | Yes |
| Intraday NAV marks | API response only | No |

## Lifecycle

1. EOD Forward + Shadow advance creates PENDING orders with `min_execution_date`.
2. While next daily candle is missing, portfolio stays `WAITING_FOR_FUTURE_MARKET_OPEN`.
3. When `INTRADAY_MARKET_ENABLED=true`, Celery beat runs `projectai.refresh_intraday_market` every `INTRADAY_REFRESH_MINUTES`.
4. Task: resolve universe (pending + open positions) → fetch board marketdata → cache → attempt open fills.
5. Eligible fill uses OPEN only; metadata records `execution_price_type=OFFICIAL_SESSION_OPEN`, `policy=SHADOW_NEXT_SESSION_OPEN_V1`, `delayed_observation`, `session_date`, `board`, `observed_at`.
6. Candle path remains fallback once the daily bar arrives (backfill / weekend catch-up).

## Late observation semantics

If the first successful poll happens **after** session open:

- Fill is still allowed **only if** the order existed **before** session open (`order.created_at < session_open_time`).
- `filled_at = observed_at` (observation time, not reconstructed open clock).
- `delayed_observation=True` in fill metadata.

V1 session open clock (when exchange open time is not on the quote): **07:00 UTC (10:00 MSK)** on `session_date`.

If `order.created_at` is on `session_date` at/after 07:00 UTC → `ORDER_CREATED_AFTER_OPEN` (cannot prove pre-open existence).

## Why no websocket

- Research stack already polls; 5-minute cadence is enough for next-session open fills.
- Websocket would add operational complexity without changing the durable decision loop.
- Redis TTL + Celery lock keep the design replaceable and easy to disable (`INTRADAY_MARKET_ENABLED=false`).

## Settings (opt-in)

```text
INTRADAY_MARKET_ENABLED=false   # default off; UI should show disabled state
INTRADAY_REFRESH_MINUTES=5
INTRADAY_CACHE_TTL_SECONDS=1200
INTRADAY_HTTP_TIMEOUT_SECONDS=20
```

## API surfaces

- `GET /api/v1/market/intraday/status`
- `POST /api/v1/market/intraday/refresh` (manual enqueue)
- `GET /api/v1/shadow/overview` — enriched with live marks + pending reasons
- `GET /api/v1/shadow/live` — live-focused read model

## Non-goals (V1)

- No Dataset / Prediction feature change
- No durable intraday candle table
- No broker execution
- No websocket stream
- No LAST as execution price
