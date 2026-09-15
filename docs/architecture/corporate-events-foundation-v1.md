# Corporate Events Foundation V1

**Status:** foundation contract (2026-09-08).  
**Scope:** types, provenance, idempotency. No Dataset V2/V3 mutation. No
prediction / shadow / `research_fi_v1` changes. No production e-disclosure
dividend provider (spike verdict: `PARTIAL_RESEARCH_ONLY`).

## Purpose

Give ProjectAI a stable place for **corporate facts** that must not be mixed
into RAW candles or silently equated with total-return entitlement.

Aligned with ADR 0005 and the existing `fundamentals` schema:

- `fundamentals.dividend_events` — versioned cash dividend disclosures
- `fundamentals.corporate_events` — structured non-cash / mechanical events
- `market.candles` — immutable RAW OHLCV

## Type inventory (foundation only)

### Already used / projected

| Type | Store | Notes |
|---|---|---|
| `SPLIT` | `corporate_events` (+ market corporate_actions projection) | Mechanical |
| `REVERSE_SPLIT` | same | Mechanical |

### Dividend path (disclosure, not candle repair)

| Concept | Store | Notes |
|---|---|---|
| Dividend disclosure versions | `dividend_events` | Recommendation ≠ approval ≠ paid |
| Optional later `DIVIDEND` marker on `corporate_events` | deferred | Only if a separate event index is needed; do not duplicate cash fields |

### Explicitly deferred (do not invent rows)

- `DENOMINATION_CHANGE`
- Ticker / SECID / board renames (instrument history, not price rewrite)
- M&A, spin-off, buyback schedules as first-class typed events

Add types only when a lawful source and PIT rules exist.

## Provenance rules

Every knowledge-bearing row needs:

1. **`source`** — stable provider code (e.g. `MOEX_ISS`, `MARKET_CORPORATE_ACTIONS`;
   future disclosure feed code when accepted).
2. **`known_at`** — availability date (when the system may know the fact).
3. Economic dates separately: `effective_date` / `record_date` / `ex_date` /
   `payment_date` — never used as a substitute for `known_at`.
4. Optional `external_id` / `source_document_id` for replay and idempotency.
5. Optional `published_at` in metadata when the source carries a publication
   timestamp finer than `known_at`.

**Forbidden:** inventing publication clocks; backdating from “today”; copying
preferred-share facts onto common shares (or vice versa).

## Idempotency

- Dividend ingest keys on issuer + instrument + source + economic anchors +
  `version` (see `run_dividend_ingestion` / `_existing_version`).
- Newer disclosures **append** a version and may `supersedes_id`; they do not
  overwrite history.
- Corporate events should use `(source, external_id)` or an equivalent natural
  key when projecting from MOEX feeds.
- Re-runs must be safe: `NO_CHANGES` when nothing new; never delete RAW market
  history as a “fix”.

## Dividend lifecycle vs total-return entitlement

These are different layers:

| Layer | Question |
|---|---|
| Disclosure lifecycle | What did the issuer recommend / approve, and when was it knowable? |
| TR entitlement | Which approved cash amounts with trustworthy `ex_date` enter gross TR? |

A recommended dividend is not yet an entitlement. Missing `ex_date` or
`amount_per_share` ⇒ TR coverage stays `PARTIAL` / `NOT_READY`. See ADR 0014.

## Point-in-Time

At decision time `t`, only rows with `known_at <= t` are visible. Labels /
forward returns remain evaluation-only and must not enter `X(t)`.

## Non-goals (this foundation)

- Implementing e-disclosure scraping or CAPTCHA bypass
- Paid disclosure APIs
- Fabricating ex-dates (`record_date - 1`)
- Crediting Shadow / Simulator cash from dividends
- Changing `pit_daily_core` or Dataset V2/V3 semantics

## Related

- `docs/research/dividend-disclosure-spike-v1.md`
- `docs/architecture/total-return-dividends-v1.md`
- `docs/adr/0014-dividend-lifecycle-separate-from-tr-entitlement.md`
- ADR 0005, ADR 0010
