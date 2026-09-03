# Data Storage

## postgres-core

Operational database for:

- `market` — instruments, RAW candles, series, DQ issues, workflows;
  `corporate_actions` stores events (H1: official MOEX `SPLIT` ingest).
  `instrument_sources` has validity windows (H2/H2.1: current-cohort ISS
  `history_from`). Candles stay RAW
  exchange OHLCV (ADR 0005). Derived adjusted / total-return series do not replace candles.
- `analytics` — feature sets, instrument/series daily features, technical feature rows, relation inputs/snapshots
- `technical` — technical runs and daily signals
- `learning` — model registry foundation; Dataset/PIT specs, runs, samples (Dataset V0)
- `portfolio` — virtual accounts/positions/trades (**future**)
- `system` — workflows, jobs, settings, event logs

Named Docker volume: `projectai_core_pgdata`.

## postgres-memory

Separate Decision Memory database with `pgvector`:

- `memory.decisions`
- `memory.decision_factors`
- `memory.decision_outcomes`
- `memory.decision_reviews`
- `memory.embeddings`

Named Docker volume: `projectai_memory_pgdata`.

Decision Memory stores immutable decision snapshots / reviews / embeddings.
It does **not** replace Core ML datasets or feature stores.
See [future-learning.md](./future-learning.md) and ADR 0002.

## Why separate?

Different lifecycle, backups, scaling path, and isolation of embeddings from market OLTP storage.

## Redis

Broker/result backend for Celery and short-lived cache/locks. Not a system of record.

## Raw data

Raw market (and later news/filing) snapshots should be retained for replay.
Object storage (e.g. MinIO/S3) can be added later without changing domain ports.

Canonical market sources: **MOEX ISS + CBR**. External CSV/Parquet/Finam/bulk dumps may
later gap-fill or cross-check with explicit provenance; they must not silently overwrite
canonical rows and must pass the same normalizer / DQ path (ADR 0005).
