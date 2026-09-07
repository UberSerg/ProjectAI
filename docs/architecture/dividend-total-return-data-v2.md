# Dividend + Total Return Data V2

## Verdict

**No viable official public dividend ingest source is wired.**

MOEX ISS probes (retained from Fundamentals V1 audit):

| Endpoint | Observed | Verdict |
|----------|----------|---------|
| `/iss/securities/{SECID}/dividends.json` | security description, not dividend table | **REJECTED** |
| `history/.../dividends` | candle history | **REJECTED** |

## What shipped

1. **DividendProvider port** (`NotReadyDividendProvider` default).
2. Coverage APIs:
   - `GET /api/v1/fundamentals/dividends/coverage`
   - `GET /api/v1/fundamentals/total-return/coverage`
   - `GET /api/v1/fundamentals/total-return/readiness`
3. Artifact `.tmp/fixed-income-dividend-enrichment-v2/total-return-readiness.json`
4. `compute_gross_total_return` wired to **real** `fundamentals.dividend_events` when present (empty store → no fabricated cash).
5. **Dataset / features unchanged** — dividends are not added to X(t).

## Celery

`projectai.sync_dividend_history` — registered only if `DIVIDEND_SYNC_ENABLED=true`, returns `NOT_READY` until an accepted provider exists.

## Research note

See `docs/research/dividend-pit-readiness-v1.md`.
