# Schema

Schema `market`:

- `instruments` — ProjectAI internal IDs; ticker is not PK. `instrument_id` is the stable
  identity. `symbol` is the current/display ticker, not a historical SECID.
- `instrument_sources` — source mapping with validity windows (`valid_from`, `valid_to`,
  half-open `valid_from <= t < valid_to`). `valid_to` NULL = current/open-ended.
  `valid_from` NULL = start unknown / current-only — **not** proven valid in 2010.
  Unique remains `(source, external_id, board)`. Column `source_metadata`.
  **H2.1:** current-cohort MOEX windows populated from ISS `history_from`
  (TQBR current; EQBR predecessor clipped to TQBR `history_from` when it overlaps).
  Not a historical universe.
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
