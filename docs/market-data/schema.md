# Schema

Schema `market`:

- `instruments` — ProjectAI internal IDs; ticker is not PK
- `instrument_sources` — unique `(source, external_id, board)`; column `source_metadata`
  (named so to avoid SQLAlchemy reserved `Table.metadata` clash; semantically the mapping metadata)
- `candles` — unique `(instrument_id, timeframe, timestamp, source)`; V1 timeframe `1d`
- `series` / `series_values` — non-OHLC series (KEY_RATE, RUONIA, CBR FX)
- `corporate_actions` — foundation table (limited ingestion in V1)
- `ingestion_batches` — batch stats + `raw_location`
- `data_quality_issues` — severity info/warning/error

Workflow state remains in `system.workflows` / `system.workflow_steps`.
