# Intelligence Stack V1 — Storage Estimates

**Owner:** Agent O (`agent/intel-o-performance`)  
**Scope:** volume / footprint planning only. No new databases.  
**Intraday bars:** reuse `market.candles` with `timeframe = '60m'`.

## Assumptions

| Parameter | Value | Rationale |
|-----------|------:|-----------|
| Bars / session (60m) | 10 | MOEX main session ~10:00–18:40; rounded up for extensions |
| Trading days / year | 250 | MOEX calendar approximation |
| Heap bytes / candle row | ~200 | NUMERIC OHLCV + text + timestamps |
| Index bytes / candle row | ~64 | share of `(instrument_id, timeframe, timestamp)` btree |
| Feature snapshot row | ~1.2 KB | `intelligence.intraday_feature_snapshots` JSONB |

Excludes WAL, bloat, replicas, and large TOAST for oversized JSONB.

Pure estimators live in `backend/app/modules/intelligence/quality/estimates.py`.

## Intraday rows / year

```text
rows_per_year = instruments × bars_per_session × trading_days_per_year
```

| Scenario | Instruments | Years | Rows / year (60m) | Rows total | ≈ Heap | ≈ Heap+index |
|----------|------------:|------:|------------------:|-----------:|-------:|-------------:|
| `research_equity_v1` | 40 | 1 | 100,000 | 100,000 | 19 MB | 25 MB |
| `research_equity_v1` | 40 | 5 | 100,000 | 500,000 | 95 MB | 126 MB |
| liquid expanded | 200 | 1 | 500,000 | 500,000 | 95 MB | 126 MB |
| liquid expanded | 200 | 5 | 500,000 | 2,500,000 | 477 MB | 629 MB |
| cautionary catalog | 1,000 | 1 | 2,500,000 | 2,500,000 | 477 MB | 629 MB |

Feature snapshots (1 row / instrument / session day):

| Instruments | Rows / year | ≈ Bytes / year |
|------------:|------------:|---------------:|
| 40 | 10,000 | ~12 MB |
| 200 | 50,000 | ~60 MB |
| 1,000 | 250,000 | ~300 MB |

## Other intelligence tables (order-of-magnitude)

| Table | Growth driver | 40-name × 1y ballpark |
|-------|---------------|----------------------:|
| `intelligence.fundamental_snapshots` | instrument × as_of × issuer_kind | low thousands |
| `intelligence.macro_snapshots` | as_of only (cross-instrument) | ~250 |
| `intelligence.intelligence_events` | news/filings cadence | tens of thousands (content-bound) |
| `intelligence.source_documents` | raw text + hash | **dominant** if `raw_text` retained |
| `intelligence.signal_outputs` | models × horizons × days | tens–hundreds of thousands |
| `intelligence.intelligence_snapshots` | instrument × as_of | ~10k |

**Document store warning:** `source_documents.raw_text` can dwarf candle storage. Prefer retention policy / external object store later; V1 keeps append-only rows in Postgres — monitor table size before wide news backfill.

## Index review (foundation migration `20261007_0027`)

### Present

| Index | Table | Columns |
|-------|-------|---------|
| `ix_intel_source_documents_known_at` | `source_documents` | `(known_at)` |
| `ix_intel_source_documents_instrument` | `source_documents` | `(instrument_id)` |
| `ix_intel_events_instrument_known` | `intelligence_events` | `(instrument_id, known_at DESC)` |
| `ix_intel_rule_eval_instrument_asof` | `knowledge_rule_evaluations` | `(instrument_id, as_of)` |

Unique constraints already cover primary lookup keys for snapshots, signals, risk, committee, macro, intraday features, and knowledge rules.

`market.candles` already has `(instrument_id, timeframe, timestamp)` — sufficient for 60m PIT reads; **do not** add a parallel candle table.

### Suggested additive indexes (orchestrator only)

Do **not** lightly rewrite foundation migration `20261007_0027` if already applied anywhere. Prefer a follow-up additive migration. See `docs/intelligence/ORCHESTRATOR_INDEX_NOTES.md`.

Justified candidates only:

1. `extracted_facts(source_document_id)` — FK join / cascade without seq scan  
2. `signal_outputs(instrument_id, as_of)` — unique leading columns are `model_id, model_version`; snapshot assembly filters by instrument+day  
3. `intelligence_events(known_at)` — market-wide / null-instrument PIT windows  
4. `refresh_runs(workflow_key, started_at DESC)` — operations status (Agent M)

Not recommended now: extra indexes on tables already covered by UNIQUE leftmost prefixes (`fundamental_snapshots`, `intraday_feature_snapshots`, `intelligence_snapshots`, `risk_assessments`).

## Coverage measurement

Runtime summary: `app.modules.intelligence.quality.build_intelligence_coverage_summary(session)`.

Domains: `daily` | `intraday` | `fundamentals` | `events` | `macro` | `knowledge`.
