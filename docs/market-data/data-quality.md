# Data Quality V1

Checks after ingest with an **explicit** mode:

## Historical / Backfill

Validates quality **inside the requested range** only:

- duplicates
- invalid OHLC
- negative volume
- missing instrument mapping
- empty responses in range
- abnormal price jumps
- missing trading days vs calendar inferred from loaded MOEX dates

Does **not** compare last candle to "today". A backfill of `2024-01-01 → 2024-02-15`
must not create `missing_recent_data` because the calendar year is later.

## Operational / Current

Used after `MarketDataUpdate` (and default manual DQ run):

- freshness of last candle (`missing_recent_data`)
- source lag (info)
- mapping / OHLC / volume / jump on latest bars

Context: `DataQualityContext(mode="historical"|"operational", date_from=..., date_to=...)`.

Results in `market.data_quality_issues`, via `/api/v1/market/data-quality`.
