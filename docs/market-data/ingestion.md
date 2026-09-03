# Ingestion

## Backfill

`POST /api/v1/market/backfill` creates a workflow and enqueues Celery task.

Flow: seed universe → download MOEX → download CBR → save RAW → upsert → DQ → finish.

## Incremental update

`POST /api/v1/market/update` uses last stored timestamp + 1 day → today.
If no history exists, falls back to default backfill start (`MARKET_DEFAULT_BACKFILL_FROM`).

## Dedup

PostgreSQL `ON CONFLICT DO UPDATE` on candle/series unique keys.

Canonical rows are MOEX ISS + CBR. Future file/Finam imports must keep `source` provenance
and must not silently overwrite those canonical series (ADR 0005). Bulk files use the same
normalizer / DQ path — not a direct INSERT into `market.candles`.

## RAW

Files under `RAW_DATA_PATH` (volume `projectai_raw_data`):

`/data/raw/{source}/{data_type}/{YYYYMMDD}/{batch_id}/{name}.json|xml`
