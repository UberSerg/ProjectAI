# Dataset V3 Design Contract (design only — no build)

**Status:** `DESIGN_DRAFT` / data gate remains `READY_FOR_DATASET_DESIGN`, **not** `READY_FOR_BUILD`.  
**Date:** 2026-09-15  
**Does not mutate:** Dataset V2, Prediction, Candidate, Policy, Risk, Shadow.

## 1. Universe

| Layer | Definition |
|---|---|
| Instrument Master | Full catalog of known instruments |
| Historical Market Universe V3 | Research cohort (board evidence) **plus** seeded historical/delisted inventory (e.g. URKA) |
| Research Universe | Pinned `research_equity_v1` (40) — separate artifact |
| Model Eligibility | Historical membership ∩ feature-data availability masks |

`universe_as_of(T)` must not be derived only from today's survivors.

## 2. Sample grain

- One row per `(instrument_or_secid, as_of_date)` at daily EOD.
- Decision-time PIT: features use only information with `known_at <= as_of`.

## 3. Targets (research candidates — not trained here)

Recommended primary exploration set:

1. **Forward gross total return** over horizon H (e.g. 20 trading days) — requires strict entitlement + high-quality dividend known_at.
2. **Excess vs CBR hurdle** — `forward_gross_TR - contemporaneous_hurdle` (investment objective alignment).
3. **Cross-sectional relative return** — rank/excess vs universe median (secondary).

Until exact/official dividend publication coverage improves, prefer **price-return / excess price-return** as interim labels with explicit `gross_tr_available=false` mask — do **not** silently mix proxy dividends into strict TR targets.

## 4. Feature families

| Family | PIT | Include V3? | Notes |
|---|---|---|---|
| Prices (raw OHLCV) | session date | YES | Immutable raw candles |
| Technical | computed ≤ as_of | YES | |
| Relations | snapshot as_of | YES optional | |
| Fundamentals RAS | known_at | YES where mapped | Banks excluded / separate mask |
| Dividends | known_at quality | MASKED | Strict only for exact/official-date |
| Macro / CBR | known_at | YES | Hurdle for excess target |
| Corporate actions (splits) | known_at / effective | YES mechanical | |
| Issuer metadata | mapping windows | YES | |

## 5. Missing policy

- Null ≠ 0.
- Missing dividend / TR → feature/target mask, not imputed cash.
- Unmapped FNS issuers → fundamentals unavailable mask (not invented ratios).

## 6. Banks

Industrial RAS ratios must not apply. Separate track or hard exclude from industrial feature pack.

## 7. Start / end

- Candidate start: `max(MIN(RAS known_at), calendar coverage start, dividend strict coverage start)`.
- Do not claim 2022-02-17 if limiting domain starts later.
- End: last complete EOD with required watermarks.

## 8. Walk-forward

Train on past → evaluate on unseen future → roll. No reshuffle of known periods as independent experience.

## 9. Version / hash

Future DatasetSpec must pin: universe version, feature manifest hash, label semantics version, calendar version, dividend provider versions.

## 10. Build blockers (current)

1. Dividend exact/official publication known_at ≈ 0% (proxy-dominated).
2. Dividend issuer coverage still MGNT+LKOH only (lawful structured IR).
3. Historical delisted inventory seeded but not full MOEX dump.
4. Gross TR strict coverage insufficient for universe-wide labels.

**Can the NEXT iteration build Dataset V3?** **NO** — until blockers 1–2 materially improve (or design explicitly scopes a narrow pilot with masks).
