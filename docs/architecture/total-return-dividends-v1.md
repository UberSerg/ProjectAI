# Total Return / Dividends Foundation V1

## Status

Foundation only (2026-09-07). **No Dataset V2 mutation. No model training.
Simulator `TOTAL_RETURN_GROSS_V1` mode is NOT wired in this PR** — old simulator runs
stay price-return only.

## Problem

`market.candles` store RAW exchange OHLCV. Dividend gaps are economic facts, not bugs.
Without an accepted dividend feed, any “total return” series would be invented.

Live audit (Fundamental Event V1): MOEX ISS dividend endpoints rejected →
`fundamentals.dividend_events` empty → coverage **NOT_READY**.

## Return kinds (ADR 0005 + this foundation)

| Kind | Meaning |
|------|---------|
| `price_return` | `(P_end / P_start) - 1` on RAW closes |
| `dividend_cash` | Sum of gross cash per share with `ex_date ∈ (start, end]` |
| `total_return_gross` | `((P_end - P_start) + dividend_cash) / P_start` |

Quality: `READY` | `PARTIAL` | `NOT_READY`.

## Code

- Domain: `backend/app/modules/fundamentals/domain/total_return.py`
- Coverage: `backend/app/modules/fundamentals/application/total_return.py`
- API: `GET /api/v1/fundamentals/total-return/coverage`
- Dividends history: `GET /api/v1/fundamentals/dividends` → `history[]`
- Coverage artifact: `.tmp/daily-autonomy-total-return-v1/dividend-coverage.json`

## Explicit non-goals

- Broker / tax / commission netting
- Overwriting `market.candles`
- Changing `pit_daily_core` v1 labels
- Crediting Shadow / Simulator cash from dividends (future task)
