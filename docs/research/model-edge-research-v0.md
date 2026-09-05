"""Model Edge Research Pack V0 — research notes.

## Research questions (kept separate)

1. **Model quality** — does the model rank future relative returns correctly?
   (Rank IC, Top-tail, stability)
2. **Portfolio translation** — does ranking become a useful portfolio under a fixed policy?
3. **Economic viability** — was equity risk worth it vs a simple cash alternative?

Do not collapse these into one score.

## Why Rank IC alone is insufficient

A long-only hysteresis policy buys the *upper* part of the ranking. Overall Spearman
can improve while Top20 realized returns worsen. That is exactly what V0 vs V1 shows
on DEVELOPMENT OOS 2017-02-01 → 2025-12-30.

## Cash hurdle

Fixed annual compounding:

    growth = (1 + r) ** (calendar_days / 365.25)
    hurdle_return = growth - 1

Default r = 10%. This is a **research benchmark**, not a promised bank deposit.
It never mutates Simulator / Shadow cash or NAV.

Rate-based CBR KEY_RATE proxy: deferred in V0 (insufficient claim as deposit yield).

## Prospective Model A/B V0

Experiment code: `PROSPECTIVE_MODEL_AB_V0`

Only intended difference: MODEL (Candidate V0 vs Candidate V1 Ranker).

- Same as_of, feature snapshot, policy, risk, capital, costs, next-open execution.
- No historical paired backfill. First paired batch only after activation watermark.
- V0 semantic: EXPECTED_RETURN (may show %). V1: RANKING_SCORE (never %).
- Experimental daily-cycle stages are non-fatal; operational V0 Forward/Shadow continue.

## External 30y archive

MIXED price semantics. Research-only descriptive context. Never scored by V0/V1,
never written into `market.candles`.
"""
