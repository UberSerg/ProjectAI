# Orchestrator note — additive indexes (Agent O)

**Branch:** `agent/intel-o-performance`  
**Policy:** prefer **not** rewriting foundation migration `20261007_0027_intelligence_stack_v1` once applied. Ship a later additive revision (e.g. `20261007_0028_intelligence_indexes_v1`) owned by the orchestrator.

## Review summary

Foundation migration indexes are adequate for document PIT (`known_at`), document-by-instrument, event-by-instrument+known_at, and knowledge evaluations by instrument+as_of. Unique constraints cover snapshot/signal primary keys. `market.candles (instrument_id, timeframe, timestamp)` already serves 60m intraday.

## Proposed DDL (additive only)

```sql
-- 1) FK join path for extraction → document
CREATE INDEX IF NOT EXISTS ix_intel_extracted_facts_document
    ON intelligence.extracted_facts (source_document_id);

-- 2) Snapshot / committee assembly: signals by instrument day
--    (uq_intel_signal_outputs leads with model_id, model_version)
CREATE INDEX IF NOT EXISTS ix_intel_signal_outputs_instrument_asof
    ON intelligence.signal_outputs (instrument_id, as_of);

-- 3) Cross-instrument / null-instrument event PIT windows
CREATE INDEX IF NOT EXISTS ix_intel_events_known_at
    ON intelligence.intelligence_events (known_at);

-- 4) Operations refresh history (Agent M)
CREATE INDEX IF NOT EXISTS ix_intel_refresh_runs_workflow_started
    ON intelligence.refresh_runs (workflow_key, started_at DESC);
```

## Explicit non-goals

- No new database / schema product.
- No separate intraday candle table.
- No rewrite of UNIQUE constraints.
- No index on every JSONB column.
