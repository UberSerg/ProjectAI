# Historical Equity Universe V2

Version: `historical_equity_universe_v2`

## Boundary hierarchy

1. `MOEX_BOARD_LISTED_FROM` — `InstrumentSource.source_metadata.listed_from`
2. `MOEX_BOARD_HISTORY_FROM` — `history_from` when listing date absent
3. `DERIVED_FROM_FIRST_CANDLE` — explicit fallback only
4. `UNKNOWN` — open-ended `eligible_to` while active

Inactive / delisted `eligible_to`:

1. `MOEX_BOARD_LISTED_TILL`
2. `INSTRUMENT_ACTIVE_TO`
3. `DERIVED_FROM_LAST_CANDLE`

## Semantics

- **Eligibility** = listing / tradability evidence for `universe_as_of(date)`
- **Feature data availability** = whether candles / features exist — separate dimension

V1 (`historical_equity_universe_v1`) remains candle-only for compatibility.

See `docs/architecture/dividend-coverage-entitlement-survivorship-v2.md`.

## V3 extension

Version: `historical_equity_universe_v3`

- Still uses V2 board / candle boundary hierarchy for the research cohort.
- Adds seeded historical equity inventory (`historical_equity_inventory_v3.json`) for
  delisted / inactive examples (e.g. URKA) that are absent from the current research 40.
- `universe_as_of(T)` = research-cohort membership ∪ historical inventory membership.
- Research Universe (`research_equity_v1`) remains a separate pinned artifact — not the
  sole definition of historical market membership.
