# Dividend Lifecycle Provider V1 (Issuer IR XLSX)

**Status:** `PARTIAL_RESEARCH_PRODUCTION_BOUNDED` (MGNT + LKOH).  
See also: `docs/architecture/dividend-coverage-entitlement-survivorship-v2.md`.

**Source code:** `ISSUER_IR_XLS_V1`  
**Does not change:** Dataset V2, Prediction, Shadow fills, `research_fi_v1`.

## Why this path exists

| Candidate | Audit |
|---|---|
| MOEX ISS `dividends.json` / history dividends | **REJECTED** (description / candles) |
| e-disclosure.ru | **REJECTED** for automation (HTTP 403) |
| Magnit IR public XLSX | **PARTIAL** — lawful, no auth, issuer-specific schema |

## Endpoints (Magnit)

- Dates: `https://www.magnit.com/files/ru/shareholders-and-investors/dividends-dates-0107-rus.xlsx`  
  Columns: period, board recommendation, shareholder approval, record (registry) date.
- History: `https://www.magnit.com/files/ru/shareholders-and-investors/dividends-history-0107-rus.xlsx`  
  Columns: period → amount per share (RUB).

Join key: normalised period label (`FY` / `M9` / `H1` / `Q1` + year). History rows marked `ИТОГ` are aggregates and are skipped.

## Semantics

| Field | Rule |
|---|---|
| `status` | `APPROVED` if shareholder approval date present; else `RECOMMENDED` if only board date |
| `amount_per_share` | From history sheet; never invent zeros |
| `record_date` | From dates sheet |
| `known_at` | Approval date, else board date |
| `known_at_quality` | `APPROXIMATE_PUBLICATION_PROXY` (meeting date ≠ disclosure timestamp) |
| `currency` | `RUB` |
| `source` | `ISSUER_IR_XLS_V1` |
| `ex_date` | Left null in ingest; optional helper `settlement_ex_date.estimate_ex_date` (PARTIAL / APPROXIMATE) |

**Recommendation ≠ entitlement.** Board-only `RECOMMENDED` rows are disclosure state, not gross total-return cash.

APPROVED rows missing `amount_per_share` **or** `record_date` are skipped.

## Wiring

- Infrastructure: `IssuerIrXlsxDividendProvider` (catalog starts with MGNT).
- Application: `get_dividend_provider()` → Composite when `DIVIDEND_SYNC_ENABLED`; otherwise NOT_READY gate with a note that IR XLSX is available when sync is on.
- Ports ingest: inject `get_ports_dividend_provider(...)` with issuer/instrument bindings.

## Settlement / ex-date

MOEX equity settlement: **T+2** before `2023-07-31`, **T+1** on/after. See `domain/settlement_ex_date.py` and ADR 0014. Do not hardcode `record_date - 1` calendar day.

## Related

- `docs/research/dividend-disclosure-spike-v1.md`
- `docs/adr/0014-dividend-lifecycle-separate-from-tr-entitlement.md`
- `docs/architecture/corporate-events-foundation-v1.md`
