# Operations — FNS fundamentals sync V1

## Enable

```env
FNS_FUNDAMENTALS_SYNC_ENABLED=true
FNS_FUNDAMENTALS_SYNC_CRON=20 5 * * 1-5
FNS_FUNDAMENTALS_PACING_MS=350
```

Optional identity/events (separate):

```env
FUNDAMENTALS_UPDATE_ENABLED=true
```

## CLI

```bash
# Inside backend container / venv
python -m app.modules.fundamentals.cli sync-identity --symbols LKOH,GAZP,MGNT,SBER
python -m app.modules.fundamentals.cli sync-fns --symbols LKOH,GAZP,MGNT,IRAO,NLMK,SBER
python -m app.modules.fundamentals.cli coverage
python -m app.modules.fundamentals.cli dataset-v3-gate
python -m app.modules.fundamentals.cli status
```

## Celery

- Task name: `projectai.sync_fundamentals_fns`
- Beat entry only when `FNS_FUNDAMENTALS_SYNC_ENABLED=true`
- Manual: `celery -A app.worker.celery_app call projectai.sync_fundamentals_fns`

## Health

| Layer | Behaviour |
|---|---|
| Process / Docker health | stays **OK** on partial FNS errors |
| Coverage | may be **DEGRADED** / PARTIAL |
| Page render | never triggers sync |

## Cohort

Default: curated equity universe (`market.universe.INSTRUMENTS` equities) — P0 research /
portfolio / shadow equities. Banks are recorded as unsupported and skipped for ingest.

## Rollback

Set `FNS_FUNDAMENTALS_SYNC_ENABLED=false`. Existing rows remain (immutable source facts);
no Dataset V2 pin is affected.
