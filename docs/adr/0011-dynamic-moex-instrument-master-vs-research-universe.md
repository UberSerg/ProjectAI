# ADR 0011 — Dynamic MOEX Instrument Master vs Frozen Research Universe

## Status

Accepted (Instrument Master + Manual Portfolio V1)

## Context

Product needs a searchable MOEX catalog (equities, funds, bonds) for Manual Portfolio and quotes, while research Dataset / prediction cohort must stay a small curated, reproducible universe. Growing `is_active` to mean “everything on MOEX” would leak bonds/funds into analytics and break walk-forward pinning.

## Decision

1. **Evolve `market.instruments` in place** — no `instruments_v2`.
2. **Instrument Master sync** upserts the MOEX catalog and source mappings; it does **not** mutate Dataset V2 or auto-add to research membership.
3. **`market.universe_memberships`** holds explicit codes; `research_equity_v1` is seeded from curated `universe.py` equities only.
4. **`InstrumentCapabilities.can_predict`** is true only for research membership (catalog ≠ predict).
5. **Empty/failed MOEX board responses must not mass-deactivate** instruments.

## Consequences

- Product catalog and research cohort diverge by design.
- Manual Portfolio may value symbols outside research without enabling prediction.
- Ops must monitor `instrument_master_sync_runs` and board-level empty/error flags.
- Analytics/learning still resolve via their own policies; membership table is the intended future pin (follow-up).
