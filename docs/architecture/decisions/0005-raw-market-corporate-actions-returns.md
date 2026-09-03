# ADR 0005: Raw market data, corporate actions, and return semantics

## Status

Accepted (2026-09-03) — Deep History **H0** architecture contract.  
This ADR does not authorize later phases. **H1** later implemented official MOEX `SPLIT`
ingest only; it does not change these decisions (RAW candles remain immutable).

## Context

Dataset/PIT V0 stores raw exchange closes and treats large price jumps as DQ discontinuities.
Deep history (direction: roughly 2014 → present) will include splits, denominations, and
dividends. Mixing those into overwritten candles, or treating every −90% move as a crash,
would corrupt Technical / Relations / ML and destroy dividend research.

Existing ADRs do not define this contract: ADR 0004 versions **derived analytics tables**,
not market facts vs return kinds vs corporate-action PIT.

## Decision

1. **`market.candles` is RAW exchange OHLCV** — the source of truth for what traded.
   Do not overwrite candles with mechanical-adjusted or total-return prices. Do not
   silently back-adjust stored history to “today’s” split basis.

2. **Three return notions stay distinct** (derived, versioned; not substitutes for raw):
   - **raw return** — exchange price movement;
   - **mechanical-adjusted return** — corrects split / reverse split / denomination only;
   - **total return** — economic holder return including cash dividends.

3. **Corporate actions are explicit events**, not candle repairs. Minimum future types:
   `DIVIDEND`, `SPLIT`, `REVERSE_SPLIT`, `DENOMINATION_CHANGE`.
   Ticker / SECID / board changes belong to **instrument / source history**, not a price rewrite.

4. **PIT:** `known_at` / `published_at` ≠ `effective_date`. Extra business dates
   (`record_date`, `payment_date`) do not imply the model knew the event.
   At decision time `t`, use CA information only if it was known `<= t`.
   A future row in the database is not knowledge at `t`.

5. **Dividends are a future Kraken edge, not noise.** Preserve the raw ex-dividend gap.
   Do not erase it from market history. Event-study features are later work.

6. **Mechanical CA ≠ dividend.** A split-like −90% (example: PLZL 2025-03-27, ~1→10)
   must not be learned as a market crash. Future adjusted layers apply explicit event/factors
   with PIT as-of `t`, not a global rewrite of historical samples.

7. **First total-return direction** (not implemented): pre-tax, pre-commission; cash
   dividend economically attributed at ex / effective event. Taxes, commissions, and
   execution costs belong to a future Simulator. **Do not assume total return is the
   first ML target.**

8. **`pit_daily_core` v1 is frozen.** New Y kinds
   (`raw_forward_return_*`, `adjusted_forward_return_*`, `total_return_*`) require a
   **new dataset spec version**. Do not silently change `forward_return_Nd` meaning.

9. **Canonical sources:** MOEX ISS + CBR. Other files/APIs may gap-fill or cross-check
   with explicit provenance; they must not silently overwrite canonical MOEX/CBR rows.
   Bulk files go through the same normalizer / DQ path as API ingest.

## Deferred (explicitly OPEN)

- First ML Candidate Y: adjusted return vs total return
- Simulator cash ledger: ex-date vs payment-date
- History depth: 2014 / 2015 / deeper
- Full PIT universe / delisted reconstruction
- Finam / unofficial bulk dumps as operational sources
- Exact `corporate_actions` migration for types beyond H1 `SPLIT`
  (H1 added `known_at`, `external_id`, identity unique; split ratio lives in `payload`)

## Consequences

- Downstream semantics changes (Analytics / Technical / Relations / Dataset) need new versions
- `current_active_instruments` remains a **fixed/current cohort** with survivorship bias
  until a PIT universe exists
- Deep history is for **different market regimes**, not row-count. Walk-forward stays mandatory
- Numerical history / features / training / simulation stay local; LLM/Polza is not the
  market-history engine

## Related

[future-intelligence-roadmap.md](../future-intelligence-roadmap.md) ·
[data-storage.md](../data-storage.md) ·
[docs/market-data](../../market-data/overview.md) ·
ADR 0004 (feature-set versioning)
