# MOEX Instrument Master V1

## Purpose

Dynamic MOEX securities catalog on top of existing `market.instruments` (no `instruments_v2`).
Research curated list in `universe.py` stays a **seed** for `research_equity_v1`, not the product catalog.

## Schema (additive)

- `market.instruments`: `instrument_subtype`, `support_level`, `primary_board`, `first_seen_at`, `last_seen_at`
- `market.universe_memberships` — explicit universe codes (e.g. `research_equity_v1`)
- `market.instrument_master_sync_runs` — sync observability (`report` JSONB)

LOTSIZE remains in `instrument_sources.source_metadata` (equities) and `investment.bond_terms.lot_size` (bonds).

## Sync

Service: `MoexInstrumentMasterSync`  
Boards: shares `TQBR`/`TQTF`/`SMAL`, bonds `TQOB`/`TQCB`.

Safety: empty or failed board responses **must not** mass-deactivate (§29–30). Deactivation runs only when every configured board returned a non-empty successful list.

Research: sync **never** auto-adds instruments to `research_equity_v1` or mutates Dataset V2.

## Capabilities

`InstrumentCapabilities` — `can_predict` only for research membership. Catalog presence ≠ predict.

## APIs

- `GET /api/v1/instruments` — search (exact > prefix > contains)
- `GET /api/v1/instruments/{id_or_secid}`
- `POST /api/v1/instruments/master/sync`
- `GET /api/v1/instruments/master/sync/status`

Existing `GET /api/v1/market/instruments` unchanged.
