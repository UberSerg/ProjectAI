# Data Quality V1

Checks after ingest:

- invalid OHLC relationships (error)
- negative volume (error)
- abnormal close jump ≥ 25% (warning)
- missing recent candle within 7 calendar days (warning; weekends/holidays may false-positive)

Results in `market.data_quality_issues`, visible via `/api/v1/market/data-quality` and UI.
