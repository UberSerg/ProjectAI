# Operations: MOEX Instrument Master Sync V1

## Enable

```env
MOEX_INSTRUMENT_MASTER_SYNC_ENABLED=true
MOEX_INSTRUMENT_MASTER_SYNC_CRON=15 17 * * 1-5
MOEX_INSTRUMENT_MASTER_STALE_HOURS=36
```

Celery beat registers `projectai.sync_moex_instrument_master_scheduled` when enabled.
Task: `projectai.sync_moex_instrument_master` (Redis lock `projectai:lock:moex_instrument_master_sync`).

## Manual / API

```bash
# async (Celery)
curl -X POST 'http://localhost:8000/api/v1/instruments/master/sync?async_mode=true'

# sync inline (operator)
curl -X POST 'http://localhost:8000/api/v1/instruments/master/sync?async_mode=false'

# status
curl 'http://localhost:8000/api/v1/instruments/master/sync/status'
```

Or worker:

```bash
celery -A app.worker.celery_app call projectai.sync_moex_instrument_master
```

## Migration

```bash
docker compose exec backend alembic -c alembic_core.ini upgrade head
# revision: 20260908_0021
```

## Startup

When enabled and last SUCCESS is older than stale hours, backend schedules a non-blocking Celery sync (same pattern as research catch-up). Boot never waits on full MOEX download.

## Failure behaviour

If all boards fail/empty → `FAILED_EMPTY`, `mass_deactivate_blocked=true`, no deactivations.
Partial board failure → skip deactivate for that run.
