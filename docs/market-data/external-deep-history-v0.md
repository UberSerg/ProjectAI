# External Deep History V0

## Purpose

Safely audit and stage an untrusted long-history daily CSV
(`30years_data_1d_interval.csv`) without mutating canonical RAW `market.candles`.

## Source identity (acceptance snapshot)

| Field | Value |
|---|---|
| File name | `30years_data_1d_interval.csv` |
| Size | ~1 050 022 377 bytes |
| SHA-256 | `6bb644d1b88a9fa83a2009d05a259d09b2ccc53648372fee355bbbff6edea009` |
| Encoding | UTF-8 |
| Delimiter | `,` |
| Columns | 88 (OHLCV + ~79 TA-Lib indicators — indicators are **not** staged) |
| Rows | ~730 614 |
| Symbols | 266 |
| Date range | 1997-05-30 → 2024-12-24 |
| Source code | `EXTERNAL_30Y_CSV_V0` |
| Parser | `external_csv_v0` |

## Price semantics

**Classification: MIXED**

Evidence:

- Overlap with MOEX RAW (~90k instrument-days): median close relative difference ≈ 0 for many names (SBER, PLZL, …).
- GMKN / TRNFP: historical external closes ≈ MOEX / 100 until the 2024 split effective date, then match — back-adjusted around splits.
- VTBR: historical external closes ≈ MOEX × 5000 until the 2024-07-15 reverse split, then match — reverse-split adjusted.
- PLZL 2025-03-27 and T 2026-04-17 probes are **after** source end → not observable in this file.

Hard rule: never merge adjusted or mixed series into `market.candles` (RAW).

## Canonical precedence

```
MOEX official RAW (market.candles)
  >
EXTERNAL_30Y_CSV_V0 staging / curated research layer
```

External data must never overwrite MOEX on overlapping dates.

## Historical universe value

- Exact current cohort matches: ~40 equities (indices IMOEX/RTSI/RGBI absent from source).
- Historical-only symbols: ~226 (broader MOEX listing set, mostly still active through 2024).
- This reduces ProjectAI’s **cohort** survivorship (43 → hundreds) but does **not** fully solve delisting bias: almost all source symbols still trade in 2024.

## Operator CLI

```bash
# from host with CORE_DATABASE_HOST=localhost (CSV is outside the container)
cd backend
python -m app.modules.market_history.cli_external audit "E:/!AI/30years_data_1d_interval.csv"
python -m app.modules.market_history.cli_external ingest "E:/!AI/30years_data_1d_interval.csv"
python -m app.modules.market_history.cli_external reconcile
python -m app.modules.market_history.cli_external curate
python -m app.modules.market_history.cli_external status
# or one explicit pipeline:
python -m app.modules.market_history.cli_external full "E:/!AI/30years_data_1d_interval.csv"
```

Default is audit-only. Re-ingest of the same SHA-256 → `NO_CHANGES`.

## API (read-only)

- `GET /api/v1/market-history/external/status`
- `GET /api/v1/market-history/external/summary`
- `GET /api/v1/market-history/external/instruments`
- `GET /api/v1/market-history/external/coverage`
- `GET /api/v1/market-history/external/reconciliation`
- `GET /api/v1/market-history/external/ml-readiness`
- `GET /api/v1/market-history/external/ca-probes`

## Tables

`market.external_sources`, `external_source_instruments`, `external_candles_daily`,
`external_audit_runs`, `external_reconciliation`, `external_curated_eligibility`,
`external_ml_readiness`.

## Known limitations

- Pre-2003 coverage is sparse (often 1–4 symbols/year).
- File ends 2024-12-24 (many symbols stop 2024-08-05).
- Dataset V2 90-feature stack is **not** fully available for early years (macro/relations/warmup).
- No automatic Dataset V3 / model retrain in this stage.
- Do not invent ticker identity transitions (YNDX→YDEX, TCSG→T).

## Possible next phase (not implemented)

Historical Universe V1 → Dataset PIT V3 (date-aware universe) → extended research models.
