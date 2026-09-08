# Fundamentals RAS via FNS GIR BO V1

**Status:** Implemented (industrial RAS ingest)  
**Date:** 2026-09-08  
**Scope:** `feature/public-fundamentals-dividends-foundation-v1`

## Summary

Industrial Russian Accounting Standards (РСБУ / RAS) reports are ingested from the
**public** FNS GIR BO JSON API (`bo.nalog.gov.ru`) into the existing
`fundamentals.financial_reports` / `financial_facts` tables.

Banks / FI are explicitly **NOT_SUPPORTED_BY_FNS_RAS_V1**.

## Identity chain

```text
MOEX SECID → emitent_id / INN (IssuerIdentity)
  → FNS search by exact INN
  → fns_org_id (+ OGRN when returned)
  → /nbo/organizations/{id}/bfo/
```

Mapping statuses: `EXACT_IDENTIFIER` | `AMBIGUOUS` | `UNMAPPED`  
(plus support: `INDUSTRIAL_RAS_V1` | `NOT_SUPPORTED_BY_FNS_RAS_V1`).

Known INN→FNS gaps (ROSN / NVTK / GMKN / PLZL): left **UNMAPPED** — name search is
ambiguous; no authoritative org override without provenance.

## PIT semantics

| Field | Meaning |
|---|---|
| `period_end` | Economic period (FY → Dec 31) |
| `known_at` | Availability date (DATE_ONLY) |
| `published_at` | Timestamp when present (`datePresent`) |

Priority for availability: `correction.datePresent` → else `actualBfoDate`.  
A report is visible at decision time `t` only if `known_at <= t`.

Online feed exposes the **latest** correction for a period →
`revision_history_incomplete=true` in metadata.

## Facts

SOURCE facts only from ОКУД line codes (e.g. 2110 revenue, 2400 net income,
1600 assets). Missing keys are omitted — **never written as 0**.  
Derived ratios (ROE/ROA/net debt) only when inputs present. **No fake EBITDA/FCF**.

RAS ≠ IFRS. Units: thousands RUB (`unit_scale=THOUSANDS`).

## Sync

- Task: `projectai.sync_fundamentals_fns`
- Flag: `FNS_FUNDAMENTALS_SYNC_ENABLED` (default false)
- Bounded / polite pacing / idempotent
- Not on page render; errors → DEGRADED coverage, process health OK

## Not in this stage

Dataset V3 creation, train, Shadow/Candidate changes, dividends production ingest,
bank fundamentals contour.
