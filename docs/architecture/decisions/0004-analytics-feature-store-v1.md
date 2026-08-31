# ADR 0004: Analytics Feature Store uses versioned typed daily feature tables

## Status

Accepted (2026-08-31)

## Context

ProjectAI needs reproducible derived features for future Relations Engine, ML, and backtesting. Market facts must stay separate from computed indicators.

## Decision

1. Store analytics in Core PostgreSQL schema `analytics` (no new database).
2. Use **wide typed daily tables** (`instrument_features_daily`, `series_features_daily`) instead of EAV for V1.
3. Version semantics via `feature_sets (code, version)` with JSON parameters.
4. Enforce point-in-time correctness and no look-ahead in application calculators.
5. Shared market analytics — no `user_id` on feature tables.

## Consequences

- Simple SQL/API/ML dataset building for daily features
- Formula changes require new feature set version
- Future intraday or cross-sectional features may add tables or versions
