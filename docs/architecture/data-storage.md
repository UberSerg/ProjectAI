# Data Storage

## postgres-core

Operational database for:

- `market` — instruments, candles, quotes, macros (future)
- `analytics` — analyzer outputs, forecasts (future)
- `portfolio` — virtual accounts/positions/trades (future)
- `learning` — model registry / retraining metadata
- `system` — workflows, jobs, settings

Named Docker volume: `projectai_core_pgdata`.

## postgres-memory

Separate Decision Memory database with `pgvector`:

- `memory.decisions`
- `memory.decision_factors`
- `memory.decision_outcomes`
- `memory.decision_reviews`
- `memory.embeddings`

Named Docker volume: `projectai_memory_pgdata`.

## Why separate?

Different lifecycle, backups, scaling path, and isolation of embeddings from market OLTP storage.

## Redis

Broker/result backend for Celery and short-lived cache/locks. Not a system of record.

## Raw data (future)

Raw market/news snapshots should be retained for replay. A dedicated object store (e.g. MinIO/S3) can be added later without changing domain ports.
