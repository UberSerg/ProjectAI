# ADR 0015 — Fundamental data uses publication-time PIT semantics

## Status

Accepted (2026-09-08).

## Context

Financial statements have an economic period (`period_end`) and a later disclosure
time. Using `period_end` as availability would leak future knowledge into decisions
before the market could know the numbers.

FNS GIR BO provides `actualBfoDate` and `correction.datePresent`.

## Decision

1. Persist `period_end` and `known_at` as separate fields.
2. Visibility rule: `known_at <= as_of`.
3. Prefer `datePresent` (date part) for `known_at`; else `actualBfoDate`.
4. Precision is **DATE_ONLY** (conservative) even when a timestamp exists; store the
   timestamp in `published_at` when available.
5. Never fabricate `known_at` from `period_end`.
6. Online FNS latest-correction-only → mark revision history incomplete.

## Consequences

- PIT acceptance tests must check before/after publication.
- Restatements version by `(known_at, report_version)`.
- Dataset / feature joins must use disclosure time, not fiscal year-end alone.
