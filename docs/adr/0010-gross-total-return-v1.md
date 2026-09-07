# ADR 0010 — Gross total return foundation (pre-tax)

## Status

Accepted (foundation). Simulator / Dataset wiring deferred.

## Context

ADR 0005 separates raw, mechanical-adjusted, and total return. Fundamental Event V1
created `fundamentals.dividend_events` but left ingestion DEFERRED (no accepted MOEX
dividend provider). Research still needs a typed contract for `price_return` vs
`dividend_cash` vs `total_return_gross` without mutating Dataset V2 or inventing fills.

## Decision

1. **Gross total return** = price change + cash dividends, **pre-tax**, **pre-commission**.
2. Cash dividends are attributed at **ex_date** for the foundation formula (payment-date
   ledger remains a future Simulator concern).
3. Quality gates: missing prices → `NOT_READY`; missing dividend amounts in-window →
   `PARTIAL`; empty dividend store for the universe → coverage `NOT_READY`.
4. **Do not** rewrite RAW candles; **do not** change `pit_daily_core` v1; **do not**
   enable Simulator `TOTAL_RETURN_GROSS_V1` in this PR.

## Consequences

- Helpers and coverage API exist for research honesty.
- Production coverage remains NOT_READY until an accepted dividend provider lands.
- Future Simulator opt-in mode must version runs separately from price-return history.
