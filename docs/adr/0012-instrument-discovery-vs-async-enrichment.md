# ADR 0012 — Instrument discovery vs async enrichment

## Status

Accepted (Fixed Income Enrichment V2)

## Context

Instrument Master sync can discover thousands of MOEX bonds. Synchronously enriching
terms/cashflows during master sync would (a) overload MOEX ISS, (b) starve EOD/intraday,
and (c) silently expand the Candidate FI pool if composition continues to query all BondTerm rows.

## Decision

1. **Discovery** (Instrument Master) upserts catalog identity only and **enqueues** enrichment jobs.
2. **Enrichment** runs as a separate Celery batch with priority queue + Redis lock + pacing.
3. **Strategy universe** for FI Candidate / Opportunity is pinned to `research_fi_v1`
   (seeded from the BondTerm sample at pin time) and does **not** auto-grow with enrichment.
4. Manual Portfolio / Shadow may value any enriched bond outside the pin.

## Consequences

- Catalog coverage can grow independently of strategy cohort.
- Ops must monitor enrichment job backlog separately from master sync.
- Explicit universe version bump required to enlarge Candidate FI pool.
- Dividend history remains a separate provider port (currently NOT_READY).
