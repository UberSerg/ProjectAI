# ADR 0015 — MOEX equity trading session calendar for entitlement

## Status

Accepted (PARTIAL)

## Context

Entitlement / ex-date derivation needs trading sessions, not Russian production workdays.
`isdayoff.ru` differs from MOEX (e.g. 2024-01-03 was a MOEX equity session).

MOEX ISS `engines/stock` `dailytable` lists only **exceptions** (~tens of rows), not a full day calendar.
`/iss/calendars*` returned HTML stubs in research probes.

## Decision

Bundle observed equity trading days from MOEX ISS history for **SBER TQBR** TRADEDATE (2021–2026) as the primary session set for entitlement walks.

Quality label: `DERIVED_FROM_MOEX_ISS_HISTORY_SESSIONS`.

Fallback: RU production calendar (`DERIVED_FROM_RU_WORKDAY_CALENDAR` / `DERIVED_FROM_RU_PRODUCTION_CALENDAR`).

Never label isdayoff-derived results as `OFFICIAL_CALENDAR`.

## Settlement regime

Unchanged evidence from ADR 0014:

- T+2 before 2023-07-31
- T+1 on and after 2023-07-31

## Consequences

Entitlement remains PARTIAL until a fuller official MOEX session dump is available and validated.
Ingest still leaves `ex_date` null unless explicitly derived.
