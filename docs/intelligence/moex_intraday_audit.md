# MOEX ISS Free Intraday Candles — Audit (Agent A)

**Date:** 2026-10-07  
**Scope:** Free public ISS candle intervals for TQBR equities. No ticks, no order book history, no paid feeds.

## Endpoint

```text
GET {moex}/iss/engines/stock/markets/shares/boards/{board}/securities/{secid}/candles.json
  ?interval={code}&from=YYYY-MM-DD&till=YYYY-MM-DD&start={offset}&iss.meta=off
```

Board-less path (`.../markets/shares/securities/{secid}/candles.json`) also returns bars; Kraken uses **explicit board** from Instrument Master / `InstrumentSource` (TQBR preferred).

## Supported intervals (observed)

| Kraken label | ISS `interval` | TQBR sample | Notes |
|--------------|----------------|-------------|-------|
| `1m` | 1 | yes | Dense; expensive to store universe-wide |
| `10m` | 10 | yes | Secondary candidate |
| `15m` | 15 | **empty** | **Do not invent 15m** |
| `60m` | 60 | yes | **Primary** |
| `1d` | 24 | yes | Daily via candles.json (history API remains canonical for EOD) |
| (4h) | 4 | empty | Rejected |
| (week) | 7 | empty on sample | Rejected for this path |

## Columns / semantics

`candles.columns`: `open, close, high, low, value, volume, begin, end`

| Field | Meaning |
|-------|---------|
| OHLC | Bar prices |
| `volume` | Traded quantity (shares/lots) |
| `value` | RUB turnover |
| `begin` / `end` | Bar window in **Moscow wall time** (naive strings) |

Kraken stores `begin` as `timestamptz` (Europe/Moscow → UTC) in `market.candles` with `timeframe='60m'`, `source='MOEX'`.

VWAP at feature time prefers `value/volume` when rows are fetched live; after DB reload only OHLCV remain, so VWAP falls back to typical-price × volume (limitation recorded in feature set docs / snapshot limitations when relevant).

## Pagination

Page size **500**. Advance `start` by 500 while `len(data) == 500`.

## Historical depth

60m history for liquid names (e.g. SBER) reaches at least **2020** (sample Jan 2020 returned bars). Exact per-security depth varies; empty ranges ⇒ no fabrication.

## Session shape (TQBR 60m, sample 2024-06-03)

About **15** hourly bars: `09:00` … `23:00` MSK (main session ~10–18, evening 19–23). The `09:00` bar is typically thin vs `10:00`.

Feature aggregation treats **10–18** as main session hours; missing hours ⇒ `None` / `PARTIAL`, never interpolated.

## Corporate actions

Interval candles are RAW exchange prints for the SECID/board window. Splits change price levels across effective dates — same invariant as daily `market.candles`: **do not rewrite history**; corporate actions stay in `market.corporate_actions`. Feature consumers must not assume split-adjusted intraday series.

## Rate / backfill practicality

- Bounded symbol×day backfills are fine for research smoke.
- Universe-wide 1m history is intentionally out of scope (storage + rate).
- Prefer `60m`; optional later `10m` only if economics justified.
- Use polite HTTP client retries already shared with market ingest (`MarketHttpClient`).

## Identity

Resolve `board` + `SECID` from current `InstrumentSource` (`MOEX` / `MOEX_ISS`), not from free-text guesses. Smoke cohort: **SBER, LKOH, MGNT**.

## Storage decision

Reuse **`market.candles`** with `timeframe='60m'`. No separate intraday candle table. Daily PIT features persist to `intelligence.intraday_feature_snapshots` (foundation migration `20261007_0027`).

## Non-goals

- Ticks / HFT / order book history  
- Push streaming  
- Fabricated 15m bars  
- Shadow / Daily Decision / broker coupling  
