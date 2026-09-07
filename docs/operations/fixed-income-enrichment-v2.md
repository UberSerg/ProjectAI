# Fixed Income Enrichment V2 — Operations

## Enable

```env
FI_ENRICHMENT_ENABLED=true
FI_ENRICHMENT_BATCH_SIZE=50
FI_ENRICHMENT_MAX_CONCURRENCY=2
FI_ENRICHMENT_PACING_MS=200
FI_ENRICHMENT_CRON=*/20 * * * *
FI_ENRICHMENT_STARTUP_P0=true
```

Dividend sync (stays NOT_READY until a provider is accepted):

```env
DIVIDEND_SYNC_ENABLED=false
```

## Migrate

```bash
alembic -c migrations/core/alembic.ini upgrade head
# revision 20260908_0022 creates enrichment jobs + seeds research_fi_v1
```

## Run a batch

- Celery beat (when enabled), or
- `POST /api/v1/fixed-income/enrichment/run`, or
- worker task `projectai.enrich_fixed_income_instruments`

## Coverage

- `GET /api/v1/fixed-income/coverage?write_artifact=true`
- `GET /api/v1/system/data-coverage`

## Safety checks

1. After enrichment of extra bonds, Candidate FI pool size = `research_fi_v1` count (unchanged).
2. Empty MOEX responses must not clear BondTerm.
3. Do not raise `FI_ENRICHMENT_BATCH_SIZE` so high that EOD/intraday starve.
4. Never enable dividend inventing; `DIVIDEND_SYNC_ENABLED` without a provider still no-ops.

## Monitoring

- `market.instrument_enrichment_jobs` status histogram (PENDING/RUNNING/SUCCESS/PARTIAL/FAILED/NO_DATA).
- System → Data Coverage tab: FI terms / cashflows / process flags.
