# Dividend publication-time research V3

**Verdict:** exact disclosure timestamps remain **unavailable** from lawful free automated sources.

## Sources checked

| Source | Result |
|---|---|
| e-disclosure.ru | HTTP 403 — rejected for automation |
| MOEX ISS sitenews `search_string` | Does not filter; returns latest site news regardless of query |
| MOEX `/iss/securities/{SECID}/news.json` | Returns security description, not news |
| IR XLSX `Last-Modified` | File-level HTTP header only — not per-event publication clock |
| Magnit / Lukoil IR XLSX body | Meeting/record dates only (proxies) |
| Additional IR (SBER/TATN/NLMK/MTSS/ALRS/…) | No lawful structured dividend XLSX accepted this iteration |

## Known_at quality after V3

Still dominated by:

- `APPROXIMATE_PUBLICATION_PROXY` (MGNT)
- `RECORD_DATE_PROXY` (LKOH)

Exact datetime / official publication date counts remain **0**.

## Implication for Dataset V3

Strict Gross TR labels cannot be universe-ready. Design contract scopes price/excess interim labels with `gross_tr_available` masks until publication clocks improve.
