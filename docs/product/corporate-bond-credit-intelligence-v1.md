# Corporate Bond Credit Intelligence V1 (product)

## User value

- Bonds catalog shows honest credit badges: **Цена / Выплаты / Кредит / Государственный долг**.
- Portfolio analysis section **«Кредитный риск облигаций»** — value-weighted coverage.
- OFZ classified as government debt, not a fabricated corporate rating.
- Clear distinction: data source unavailable vs issuer unrated.

## Non-goals (V1)

- Live ingest of agency ratings (provider NOT_READY)
- Auto buy/sell from ratings
- Fake scores / inferred ratings from YTM
- Expanding research_fi_v1 Candidate universe

## UI surfaces

1. `/bonds` — Catalog V2 over Instrument Master
2. `/bonds/:secid` — detail works for master-only rows; enqueues FI enrichment once
3. My Portfolio → Analysis → credit section
4. System → Data Coverage → credit + FI enrichment job stats
