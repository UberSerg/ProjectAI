# Historical Equity Universe V1 (Survivorship Contract)

**Version code:** `historical_equity_universe_v1`  
**Module:** `app.modules.market.application.historical_universe`

## Purpose

Provide a point-in-time **eligible equity set** that does not silently include
instruments before their observed price history (and closes the window after
delisting/inactivity when candles end).

This is a **contract over existing candles**, not a new membership table and not
a mutation of `research_fi_v1`, Dataset V2, Prediction, or Shadow history fills.

## Cohort

1. Prefer instruments in `research_equity_v1` universe membership.
2. If that set is empty, fall back to all `asset_class=equity` instruments that
   have at least one daily (`1d`) candle.
3. Callers may pass an explicit `instrument_ids` list.

## Eligibility fields

| Field | Meaning | Quality |
|---|---|---|
| `eligible_from` | First daily candle date | `DERIVED_FROM_FIRST_CANDLE` |
| `eligible_to` | Last daily candle date if instrument is inactive (`is_active=false`) or has `active_to`; else `None` (open-ended) | `DERIVED_FROM_LAST_CANDLE` or `UNKNOWN` |
| `provenance` | Basis strings + candle bounds + activity flags | — |

## API

```python
build_historical_equity_universe(session, version=HISTORICAL_EQUITY_UNIVERSE_V1, ...)
universe_as_of(session, as_of: date, version=HISTORICAL_EQUITY_UNIVERSE_V1, ...) -> list[instrument_id]
```

`universe_as_of` returns ids where `eligible_from <= as_of` and
(`eligible_to is None` or `as_of <= eligible_to`).

## Non-goals

- Inventing official listing/delisting calendars beyond candle + instrument flags
- Expanding or rewriting `research_fi_v1`
- Changing Dataset / Prediction / Shadow semantics

## Related

- `docs/architecture/corporate-events-foundation-v1.md`
- Research survivorship notes in future-intelligence roadmap (deep history ≠ independent experience)
