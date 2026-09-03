# Schema

Schema `market`:

- `instruments` — ProjectAI internal IDs; ticker is not PK. `instrument_id` is the stable
  identity. Ticker / SECID / board are **not** eternal identity (future source
  `valid_from` / `valid_to` — H2, not implemented).
- `instrument_sources` — unique `(source, external_id, board)` today (current mapping only);
  column `source_metadata`
  (named so to avoid SQLAlchemy reserved `Table.metadata` clash; semantically the mapping metadata)
- `candles` — unique `(instrument_id, timeframe, timestamp, source)`; V1 timeframe `1d`;
  **RAW** exchange OHLCV (ADR 0005). No adjustment columns.
- `series` / `series_values` — non-OHLC series (KEY_RATE, RUONIA, CBR FX)
- `corporate_actions` — events, not a price-repair table. **H1:** official MOEX ISS
  splits feed (`event_date` = effective/`tradedate`; `known_at` NULL). Domain type is
  `SPLIT` if `after/before > 1`, `REVERSE_SPLIT` if `0 < after/before < 1`. Ratio lives
  in `payload`. `DENOMINATION_CHANGE` / `DIVIDEND` are not classified from this feed.
- `ingestion_batches` — batch stats + `raw_location`
- `data_quality_issues` — severity info/warning/error

Workflow state remains in `system.workflows` / `system.workflow_steps`.
