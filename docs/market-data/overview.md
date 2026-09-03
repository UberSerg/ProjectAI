# Market Data V1

ProjectAI Market Data V1 loads and stores factual market history for later analytics.

**H0 contract (ADR 0005):** `market.candles` stores **RAW** exchange OHLCV. Do not overwrite
with adjusted or total-return prices. **H1:** official MOEX ISS splits feed is ingested as `market.corporate_actions`
(`SPLIT` / `REVERSE_SPLIT` by factor). Events explain jumps; they do not rewrite candles.
`DIVIDEND` ingest, adjusted prices, and total return are not implemented. **H2:**
`instrument_sources` has `valid_from`/`valid_to` so as-of SECID/board can be resolved.
**H2.1** fills trusted ISS `history_from` windows for the current cohort only.
**H3** loads official RAW ISS/CBR history for those proven windows.
Deep raw history is **not** ML-ready (pending H4/H5/H6).
This is not a historical universe. MOEX ISS + CBR are canonical sources.

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
- `MarketSplitsIngest` (`POST /api/v1/market/corporate-actions/splits`) — official ISS SPLIT only
- `DataQualityCheck`

## Docs

See `docs/market-data/` for schema, ingestion and quality details.
