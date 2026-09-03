# Ingestion

## Backfill

`POST /api/v1/market/backfill` creates a workflow and enqueues Celery task.

Flow: seed universe → download MOEX (current/open-ended source mapping) → download CBR → save RAW → upsert → DQ → finish.

Historical as-of SECID/board resolution is available for future importers
(`resolve_source_as_of`). Current ingest does not walk historical mappings.

## Incremental update

`POST /api/v1/market/update` uses last stored timestamp + 1 day → today.
If no history exists, falls back to default backfill start (`MARKET_DEFAULT_BACKFILL_FROM`).

## Dedup

PostgreSQL `ON CONFLICT DO UPDATE` on candle/series unique keys.

Canonical rows are MOEX ISS + CBR. Future file/Finam imports must keep `source` provenance
and must not silently overwrite those canonical series (ADR 0005). Bulk files use the same
normalizer / DQ path — not a direct INSERT into `market.candles`.

## SPLIT corporate actions (H1)

`POST /api/v1/market/corporate-actions/splits` fetches
`/iss/statistics/engines/stock/splits.json` (`tradedate`, `secid`, `before`, `after`).

Flow: MOEX provider → draft (source = ISS splits feed) → domain type from factor
(`after/before`: `>1` SPLIT, `<1` REVERSE_SPLIT, `=1` rejected) → resolve via
`instrument_sources` → idempotent upsert → annotate matching `abnormal_price_jump`
with the normalized type. Unknown SECIDs are counted, not auto-created.
`known_at` stays NULL. RAW candles are not rewritten. Dividends / adjusted prices /
total return / `DENOMINATION_CHANGE` are not ingested here.

## RAW

Files under `RAW_DATA_PATH` (volume `projectai_raw_data`):

`/data/raw/{source}/{data_type}/{YYYYMMDD}/{batch_id}/{name}.json|xml`
