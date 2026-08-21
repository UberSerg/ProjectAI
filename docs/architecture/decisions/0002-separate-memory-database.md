# ADR 0002: Separate Decision Memory Database

## Status

Accepted

## Context

Decision snapshots, outcomes, reviews, and embeddings have a different lifecycle and query profile than market OLTP data.

## Decision

Run `postgres-memory` (pgvector) separately from `postgres-core`, with independent migrations, backups, and connection settings.

## Consequences

Backend maintains two engines/sessions. Memory can later move to another host without rewriting market storage.
