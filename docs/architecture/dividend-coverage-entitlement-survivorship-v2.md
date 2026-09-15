# Dividend Coverage + Entitlement + Survivorship V2

**Status after this iteration:** Dataset V3 remains **PARTIAL** / `READY_FOR_DATASET_DESIGN` — **not** `READY_FOR_BUILD`.

## What changed

### Dividends (Coverage V2)

| Issuer | Source | Format | known_at quality | Verdict |
|---|---|---|---|---|
| MGNT | Magnit IR XLSX (dates+history) | `magnit_dates_history` | `APPROXIMATE_PUBLICATION_PROXY` | PARTIAL |
| LKOH | Lukoil IR XLSX (declared sheet) | `lukoil_declared_single` | `MEETING_DATE_PROXY` or `RECORD_DATE_PROXY` | PARTIAL |
| Other research cohort | — | — | — | SOURCE_NOT_FOUND / unsupported |

- Source code remains `ISSUER_IR_XLS_V1` (unified lifecycle table).
- Common ≠ preferred: Lukoil `ап` rows are never mapped onto `LKOH` common.
- Celery `sync_dividend_history` now ingests the bounded catalog when `DIVIDEND_SYNC_ENABLED`.

### Trading calendar / entitlement

- Bundled RU production day-off calendars (isdayoff.ru bitmasks) for 2021–2026.
- Quality: `DERIVED_FROM_RU_PRODUCTION_CALENDAR` / entitlement `DERIVED_FROM_RU_WORKDAY_CALENDAR`
  (isdayoff.ru — **not** an official MOEX session calendar).
- Settlement: T+2 before `2023-07-31`, T+1 on/after (ADR 0014).
- Not a MOEX session dump — still PARTIAL.

### Survivorship V2

- Contract: `historical_equity_universe_v2`.
- Prefer `InstrumentSource.source_metadata.listed_from` / `history_from`.
- Candle first/last is **explicit fallback** only.
- Eligibility ≠ feature data availability.

### Gross Total Return

- Domain helpers unchanged in spirit; strict mode can exclude approximate known_at when loading cash points.
- Dataset V2 untouched.

## Related code

- `issuer_ir_xlsx_dividend_provider.py`, `lukoil_ir_xlsx.py`
- `entitlement.py`, `trading_calendar.py`, `ru_trading_calendar.py`
- `historical_universe.py` (v1+v2)
- Data Coverage UI expandable ML reliability section

## Hard non-goals (unchanged)

No Dataset V3 build, Candidate V2, Prediction/Policy/Risk/Shadow mutation.
