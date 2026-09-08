# Credit Intelligence V1

## Purpose

Honest storage and APIs for corporate/issuer/issue credit ratings **without inventing data**.

Production provider status after live probe (2026-09-08): **NOT_READY** /
`READY_REQUIRES_ACCESS` (MOEX CCI passport denied; ACRA paid CSV; Expert RA no free bulk API).
Unofficial scrapes are forbidden.

## Schema

Tables live in PostgreSQL schema **`investment`** (next to `bond_terms` / cashflows):

| Table | Role |
|-------|------|
| `credit_agencies` | Agency dictionary (ACRA, EXPERT_RA, NCR, MOEX_CCI) |
| `credit_rating_observations` | Append-only ISSUER\|ISSUE observations |
| `credit_sync_jobs` | Sync queue (gated; no-ops while provider NOT_READY) |

Issuer identity remains in `fundamentals.issuers`. This store holds agency rating facts.

## Availability statuses

Do **not** overload `UNKNOWN`:

| Status | Meaning |
|--------|---------|
| `SOURCE_NOT_READY` | No accepted live provider / credentials |
| `NO_RATING_FOUND` | Accepted provider searched; empty |
| `MAPPING_FAILED` | Rating exists but subject mapping failed |
| `CURRENT_RATING_AVAILABLE` | Stored agency rating with scale/date |
| `GOVERNMENT_RUSSIAN_FEDERAL` | OFZ / RF government debt category — **not** fake AAA |

## Provider

`CreditRatingProvider` Protocol + `NotReadyCreditRatingProvider` (mirrors DividendProvider).

- Env: `CREDIT_SYNC_ENABLED=false` (default)
- Celery: `sync_credit_ratings` — DISABLED or NOT_READY no-op
- APIs: `GET /credit/coverage`, credit section in `GET /system/data-coverage`

## Boundaries

Credit ≠ valuation eligibility ≠ strategy eligibility (see ADR 0013).
No Dataset V3, no training, no Shadow policy change, no broker, no scrape.
