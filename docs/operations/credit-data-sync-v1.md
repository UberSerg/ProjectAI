# Credit data sync V1 (operations)

## Flags

| Env | Default | Effect |
|-----|---------|--------|
| `CREDIT_SYNC_ENABLED` | `false` | Beat schedule + task gate |
| `CREDIT_SYNC_CRON` | `45 4 * * 1-5` | Celery beat cron (UTC) |

## Behaviour

1. `CREDIT_SYNC_ENABLED=false` → task returns `{status: DISABLED}`, ingested=0.
2. Flag true but provider NOT_READY → `{status: NOT_READY}`, ingested=0.
3. No HTML scrape; no yield/name inference; no OFZ→AAA fabrication.

## Readiness check

```http
GET /api/v1/credit/coverage
GET /api/v1/system/data-coverage
```

Inspect `credit.provider.status` and `processes.credit_sync_enabled`.

## Live acceptance (future)

Requires commercial access (MOEX CCI MicexPassport and/or ACRA CSV / Expert RA feed).
Until then V1 remains structurally complete with empty observations.
