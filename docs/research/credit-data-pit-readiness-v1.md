# Credit data PIT readiness V1

## Probe verdict (2026-09-08)

See `.tmp/corporate-credit-fi-coverage-v1/credit-source-audit.json`.

| Source | Decision |
|--------|----------|
| MOEX CCI `/iss/cci/rating/*` | REJECTED — empty body, `X-MicexPassport-Marker: denied` |
| ACRA structured feed | REJECTED — paid commercial CSV |
| Expert RA | REJECTED — no free bulk API confirmed |
| Unofficial scrapes | FORBIDDEN |

## PIT rules when a provider becomes READY

1. Persist `action_date`, `known_at`, `known_at_quality` separately.
2. Decision at time `t` may only use observations with `known_at <= t`.
3. Do not backfill “current” ratings into past decision snapshots.
4. Agency scales are not interchangeable without explicit mapping (`mapping_quality`).

## Current readiness

Provider: **NOT_READY**. Domain + storage + APIs ready for future credentials.
