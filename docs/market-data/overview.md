# Market Data V1

ProjectAI Market Data V1 loads and stores factual market history for later analytics.

**H0 contract (ADR 0005):** `market.candles` stores **RAW** exchange OHLCV. Do not overwrite
with adjusted or total-return prices. Corporate actions (when ingested later) are separate
events. MOEX ISS + CBR are canonical sources.

## Sources

- **MOEX ISS** — equities (TQBR) and indexes (SNDX) daily history
- **Bank of Russia** — official FX (`XML_dynamic.asp`) and KEY_RATE / RUONIA via DailyInfo SOAP

Note: legacy `XML_KeyRate.asp` returns 404; KeyRate uses SOAP `KeyRateXML`.

## Storage

- PostgreSQL `market.*` tables (instruments, candles, series, batches, DQ)
- Raw payloads on Docker volume `/data/raw/{moex|cbr}/...`

## Pipelines

- `MarketDataBackfill`
- `MarketDataUpdate` (incremental; scheduler gated by `MARKET_UPDATE_ENABLED=false` by default)
- `DataQualityCheck`

## Docs

See `docs/market-data/` for schema, ingestion and quality details.
