# ADR 0014 — Dividend lifecycle separate from total-return entitlement

## Status

Accepted (research foundation, 2026-09-08).

## Context

`fundamentals.dividend_events` already models announcement / recommendation /
approval / record / ex / payment dates plus versioning. Gross total-return
helpers (ADR 0010) attribute cash at `ex_date` when present.

The e-disclosure spike (`PARTIAL_RESEARCH_ONLY`) confirms there is still **no**
accepted free automated disclosure feed. Risk: collapsing “board recommended
₽X” into “holder was entitled to ₽X on ex-date” would invent economics and break
PIT honesty.

## Decision

1. **Disclosure lifecycle ≠ TR entitlement.**  
   Recommendation / approval / paid are disclosure states. Entitlement for
   `total_return_gross` is a **downstream filter**: typically approved (or paid)
   cash with a trustworthy `ex_date` and `amount_per_share`, visible under
   `known_at <= t`.

2. **Do not fabricate `ex_date`.**  
   Especially forbid `ex_date = record_date - 1` calendar day. MOEX settlement
   moved T+2 → T+1 from **2023-07-31**; any derivation must use a versioned
   trading-calendar rule with provenance — or leave `ex_date` null.

3. **Share-class mapping is mandatory.**  
   SBER ≠ SBERP (and TATN ≠ TATNP). Ambiguous class → reject the row.

4. **Preserve publication availability.**  
   `known_at` / `published_at` come from disclosure provenance, not from
   economic dates.

5. **No production provider until READY.**  
   Spike verdict is not `READY_FOR_PRODUCTION_V1`; keep ingest DEFERRED /
   NOT_READY. Dataset V2/V3 stay unchanged.

## Consequences

- Coverage APIs remain honest when `dividend_events` is empty.
- Future lawful providers plug into the existing port without redefining TR.
- Simulator cash credit and Dataset total-return labels remain separate future
  tasks with explicit version bumps.

## Related

- ADR 0005 — raw market / corporate actions / returns  
- ADR 0010 — gross total return foundation  
- `docs/research/dividend-disclosure-spike-v1.md`  
- `docs/architecture/corporate-events-foundation-v1.md`
