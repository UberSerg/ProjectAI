# Dividend PIT Readiness V1 (research)

## Question

Can ProjectAI build Point-in-Time dividend history suitable for gross total return
and (later) walk-forward evaluation without look-ahead?

## Findings

1. MOEX ISS “dividends” paths do **not** return dividend tables (REJECTED).
2. No accepted public provider is configured in the current environment.
3. Existing `fundamentals.dividend_events` schema already supports:
   - `ex_date`, `known_at`, versioning / supersedes
   - issuer + instrument linkage
4. Without a lawful source of `known_at` / announcement timestamps, historical PIT
   reconstruction remains **NOT_READY**.

## Readiness criteria (future)

- Accepted provider with reproducible fetch + audit.
- Idempotent upsert; no fabricated ex-dates/amounts.
- `known_at` quality better than CURRENT_STATE_ONLY where possible.
- Coverage ratio vs equity price history ≥ product threshold.
- Explicit opt-in; Dataset V2 stays price-only until a separate feature version bump.

## Current product stance

UI and APIs show **NOT_READY** with reasons. Empty dividend sections are honest.
`compute_gross_total_return` works with fixtures / stored events but does not invent them.
