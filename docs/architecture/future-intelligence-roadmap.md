# ProjectAI Future Intelligence Roadmap

## Status

**Status: Planned / Research**

**Not implemented yet.**

This document consolidates architectural analysis for future intelligence layers. It is **not** a description of shipped production capabilities.

Current production architecture ends at Market → Analytics → Relations V1 → **Technical Agent V1 (implemented on `feature/technical-v1`)**. Dataset/PIT Join and later layers remain design intent until an explicit stage begins.

Related research: [Market Regime / Market State V0 Research](./market-regime-v0-research.md).

---

## Current foundation

```text
Market Data V1
        ↓
Analytics Feature Layer V1  (basic_daily, PIT, quality flags)
        ↓
Relations Engine V1
        ↓
Technical Agent V1          (**Implemented** — see `technical-agent-v1.md`)
```

**What exists today (grounded):**

| Layer | Role | Notes |
|-------|------|--------|
| Market Data | Factual candles, series, DQ issues | Observation-date alignment; no true publication timestamps for sparse events; no adjusted prices in V1 |
| Analytics Feature Layer | Versioned derived daily features (`feature_sets`, wide typed tables) | ADR 0004; no look-ahead in calculators; `log_return_1d`, returns, volatility, drawdown, volume features |
| Relations Engine V1 | Statistical relations with `as_of_date` snapshots | Shipped; ML-ready; does **not** recommend trades |
| Technical Agent V1 | Deterministic technical features + rules_v1 signals | Shipped; pure TechnicalModel; PIT frozen input; historical signals |

**Domain ports:**

- `TechnicalModel` + typed `TechnicalModelInput` / `TechnicalModelOutput` (`rules_v1` / RuleBasedTechnicalModel)
- `PortfolioPolicy`, `LLMProvider`
- `learning.model_registry` foundation (no training loop yet)

**Explicitly not implemented yet:** Fundamental Intelligence, Market Regime, Dataset/PIT Join pipeline, ML Candidate, Meta Model, Recommendations / BUY-SELL.

**Next planned stage:** Dataset / PIT Join V0.

---

## Technical Agent V1

Technical Agent is a **consumer** of Analytics (and optionally Relations later). It must not become a second feature store or a duplicate of Relations.

### Analytics features to use (state @ t)

From `analytics.instrument_features_daily` under active `feature_sets(code=basic_daily, version=1)`:

**Core:**

- `log_return_1d` — same family Relations V1 uses for instruments
- `return_1d` / `return_5d` / `return_20d` — momentum horizons
- `volatility_5d`, `volatility_20d`
- `drawdown_20d`
- `volume_change_1d`, `volume_zscore_20d`
- `close`, `volume` — context / normalization only, not “the signal”
- `is_valid`, `has_sufficient_history`, `quality_flags` (especially `price_discontinuity`)

**Series context (as-of join date ≤ t, already supported by Feature Layer):**

- FX pct_change, KEY_RATE / RUONIA absolute_change — macro context in metadata/factors; not required inside score V1

**Row policy:** prefer `is_valid=true`; discontinuities → exclude or explicit confidence penalty (never silent ignore).

### Classical indicators (deterministic, narrow set)

Do **not** port legacy “RSI/MACD everything” catalogs. Compute backward-looking on trading observations only.

**P1 (V1):**

- SMA/EMA distance: `(close − SMA_20)/SMA_20`, `(close − EMA_20)/EMA_20`
- RSI_14 (Wilder) — overbought/oversold **factor**, not BUY signal
- ATR_14 / close — normalized volatility (complements analytics `vol_*`)
- Volume confirmation: existing `volume_zscore_20d`; optional OBV slope over 10/20 obs

**P2 (later, new `feature_set` version — do not mutate `basic_daily` v1):**

- MACD histogram (12/26/9) only if a crossover factor is needed
- Bollinger %B / bandwidth — partly overlaps vol + drawdown
- Stochastic — weak daily edge without volume context

**Out of V1:** Ichimoku, Fibonacci, LLM pattern recognition, intraday indicators (`timeframe=1d` fixed).

**Storage intent:** new feature set, e.g. `technical_daily v1` (ADR 0004 spirit: immutable semantics per `(code, version)`). Never rewrite `basic_daily` v1 formulas in place.

### Deterministic V1 vs later ML

| Phase | What runs | Where |
|-------|-----------|--------|
| V1 | Indicator calculator + `RuleBasedTechnicalModel` (explicit weights/thresholds) → `score ∈ [-1,1]`, `confidence` from history coverage + quality | `modules/technical/application`; persistence with `(instrument_id, as_of_date, model_code, model_version)` |
| Later | Same port `TechnicalModel.predict`; CatBoost/XGBoost adapter | Training in `modules/learning`; artifacts in `learning.model_registry` |

LLM / Polza: **never** compute indicators or scores. Optional later layer: human-readable rationale over already computed numbers (not part of the agent contract).

### CRITICAL: TechnicalModel must stay pure

**Wrong (rejected):**

```text
TechnicalModel.predict(...)
        ↓
loads features from PostgreSQL / Feature Store itself
```

**Correct:**

```text
TechnicalSignalService  (application / orchestration)
        ↓
loads point-in-time features (market + analytics [+ optional relations])
        ↓
builds frozen TechnicalModelInput
        ↓
TechnicalModel.predict(input)   ← pure, no I/O
```

Rules:

1. `TechnicalModel` does **not** open DB sessions, call repositories, or read Redis.
2. All I/O and PIT joins live in a service / use-case layer.
3. `TechnicalModelInput` is a **frozen** feature vector (+ identifiers / as_of).
4. **Same input + same model version ⇒ same output** — required for unit tests, backtests, reproducibility, future ML adapters, and champion/challenger comparison.

Existing port shape (`ticker`, optional `as_of`, `features` → `score` / `confidence` / `direction` / `metadata`) already supports purity; V1 should harden `as_of` as required at the service boundary and pin `model_code` / `model_version` in output metadata.

### Output contract (V1 intent)

Keep / refine the domain port:

**Input (assembled by service, not by model):**

- `instrument_id` preferred (ticker for UX)
- `as_of` — required for PIT at the service boundary
- `feature_set_ref` — which analytics (and later technical) versions were loaded
- `features` — **preloaded** frozen vector (never “empty means load from store” inside the model)

**Output:**

- `score` ∈ [-1, 1]
- `confidence` ∈ [0, 1]
- `direction`: `neutral` | `bullish` | `bearish`
- `metadata` scalars: `as_of_date`, feature set refs, `model_code` / `model_version`, short factor contributions, quality summary, `horizon_hint` (`1d`|`5d` — meaning of score, not a return forecast)

**Workflows (future):** `TechnicalSignalBackfill` / `Update` patterned after FeatureBackfill — Celery + workflows. Still **no** BUY/SELL recommendations.

Relations: optional factors from `relation_snapshots @ as_of` later; Technical V1 can start on Analytics alone.

---

## Fundamental Intelligence

Corporate reports ≠ RSS news sentiment. Planned module boundary today is `news` (“news/fundamental”); reporting should get a dedicated **`fundamentals`** contour in Core DB, not Memory DB and not the analytics feature store.

### Pipeline (design only)

```text
Corporate Reports
        ↓
Raw filing (PDF / XBRL / HTML)     — object store /data/raw/...
        ↓
Parser (+ optional LLM assist)
        ↓
Structured Financial Facts         — Core schema `fundamentals`
        ↓
Derived Fundamental Features       — versioned analytics-like features
        ↓
Relations inputs / Event Study / ML / Expert Agent
```

### Storage principles (conceptual — no tables now)

- **`fundamentals.report_filings`:** instrument, report type, period_end, fiscal period, currency, accounting standard, **`published_at`**, source, raw location, restatement chain, ingested_at
- **`fundamentals.report_metrics`:** filing-scoped metric codes (revenue, EBITDA, net income, EPS, FCF, …) with value/unit/scale
- **PIT snapshots / as-of views:** metric visible at calendar date `t` only if `published_at::date ≤ t`; restatements preserve “what was known at t”

Raw filing blobs stay out of `analytics.*`. Analytics (or a fundamentals feature set) holds only derived numbers (growth, surprise, days-since-event), versioned like other feature sets.

### Critical fields

| Concept | Rule |
|---------|------|
| `published_at` | When the market could know the fact — **mandatory** from first ingest |
| `period_end` | End of reporting period — **never** substitute for market-known time |
| Restatements | Chain filings; PIT uses the filing known at `t`, not the latest rewrite |
| Actual / previous / consensus / guidance | Separate namespaces or tables — do not mix |

Known foundation gap: Market/Analytics V1 align sparse series by observation date, not true publication time. Fundamentals must not repeat that mistake.

### Actual vs previous / consensus / guidance

- **actual** — from filing after `published_at`
- **previous / YoY / QoQ** — deterministic diffs only if prior actual was already published by `as_of`
- **consensus** — external estimate with its own snapshot/publish time; otherwise banned from strict PIT datasets
- **guidance** — management outlook event with `published_at`; not an “actual”

Surprise features: `(actual − consensus) / |consensus|` only when both are known at `t`.

### How fundamentals become Relation Inputs (later)

Extend Relations **input families** without rewriting the calculator:

- families like `fundamental_event` / `fundamental_series`
- numeric keys only (e.g. earnings surprise z, revenue YoY, days since earnings)
- explicit transform / alignment (event as-of ffill until next; impulse decay)
- visible only when `published_at ≤ t`

Do not dump full XBRL into the correlation matrix.

### Polza / LLM vs deterministic code

| Deterministic | LLM (Polza via `LLMProvider`) |
|---------------|-------------------------------|
| XBRL/table parse → numbers | Extract structured JSON from messy PDF with schema validation + DQ path |
| Ratios, growth, surprise, calendar features | Classify guidance tone / risk themes → enum/score |
| Quality flags | **Never** invent EPS, dates, or BUY/SELL; **never** be source of truth for `published_at` |

Numeric feature path → Core. Raw LLM prose → Decision Memory only as explanation, if at all.

### CRITICAL ADD: Fundamental Event Study

Corporate reporting is **sparse**. Rolling correlation alone is often the wrong tool around filings.

Future analytics must support **two** complementary modes:

1. **Continuous Relation Inputs** — time series / as-of features in the Relations engine (as above).
2. **Discrete Event Study** — event-centered outcome windows.

Conceptual studies (design only — **not** implementing now):

```text
EBITDA surprise at event t
        ↓
return t+1, t+3, t+5, t+10, t+20

Revenue surprise at t
        ↓
future returns

Guidance change at t
        ↓
future returns

Net Debt / EBITDA change at t
        ↓
future returns
```

Event Study needs: event id, `published_at` / event time, instrument universe, PIT-safe pre-event state, post-event return windows on the trading calendar, and explicit version pins for label formula. It is a **separate research / dataset product** from continuous Relations snapshots — not a substitute for them.

---

## ML-ready architecture

### Target row shape

```text
state @ t
+ analytics @ t
+ relations @ t
+ technical @ t
+ fundamentals known @ t
+ market regime @ t
        ↓
target return t+N
```

**Hard rule:** features `X` use only information available at or before `t`. Labels use the future strictly after `t` and live **outside** the feature row.

Verdict from prior review: the **scaffold is suitable** (market ≠ analytics; versioned feature sets; Relations `as_of` snapshots by design). A full dataset builder is **not** implemented yet. Honest PIT joins are possible today for market+analytics; relations@t after Relations V1 ships as designed; regime@t after Market State research/implementation.

### Version pins (every dataset row / model card)

- `feature_set` code / version (+ preferably `feature_run_id`)
- `relation_set` code / version (+ preferably `relation_run_id`)
- technical `model_code` / `model_version`
- fundamental snapshot policy (+ max `published_at` ≤ t when present)
- market regime model / version (when present)
- `dataset_code` / `dataset_version`
- `label_horizon_N`, label formula, trading calendar semantics
- quality policy (which flags excluded)
- source / market watermark (replay)

### Look-ahead holes to keep documented

- Sparse series without true `published_at`
- Corporate actions / unadjusted prices around splits
- Relations `best_lag` chosen with future information → leakage if used as ML features
- Using backward `return_*` columns as if they were forward labels
- Silently mutating feature/relation semantics without a version bump

See also: [Market Regime V0 Research](./market-regime-v0-research.md) for `regime_detected_at_t` vs ex-post labeling.

---

## Risks / Architectural Traps

1. **Technical Agent as a second Feature Store** — ad-hoc candle math without versioning → unreproducible ML. Keep derived indicators in versioned feature sets; keep `TechnicalModel` pure.
2. **Live / “today” Relations recompute treated as historical** — must use stored `as_of` snapshots; recomputing now and pretending it was known at `t` is leakage.
3. **`best_lag` / exploratory lead-lag as ML features** without PIT constraint — fix lag on past-only windows or use fixed lags.
4. **Fundamentals keyed by `period_end` instead of `published_at`** — classic earnings look-ahead bias.
5. **LLM as source of financial numbers or dates** without structured validation — Polza assists parse/classify; Core stores validated facts.
6. **Mixing adjusted and unadjusted prices silently** — breaks features and labels; needs an explicit later stage decision.
7. **Mutating feature / relation semantics without version bump** — forbidden; new `(code, version)` for formula changes.
8. **Premature ML DB / feature bus / microservices** — contradicts modular monolith and ADR 0004; stay in Core analytics/learning until proven otherwise.

Additional traps from prior analysis (still valid): Decision Memory embeddings in shared analytics tables; Recommendations/BUY-SELL before stable PIT datasets; blocking Technical on unfinished Relations (Technical can start on `basic_daily`).

---

## Recommended sequence

This is a **roadmap**, not an immutable plan. It may change after results of earlier stages.

| # | Stage | Intent |
|---|--------|--------|
| 1 | **Relations Engine V1** | **In progress.** Inputs, `as_of` snapshots, versioned sets, quality — foundation for `relations@t`. Do not divert this work into the stages below. |
| 2 | **Technical Agent V1** | Deterministic technical factors + `rules_v1`; pure `TechnicalModel`; optional Relations factors later |
| 3 | **Dataset / PIT Join V0** | Honest historical ML dataset export **without** full training — proves the join contract |
| 4 | **Fundamental Intelligence V1** | Filings + `published_at` + structured metrics; Event Study design; optional relation inputs |
| 5 | **ML Candidate V0** | CatBoost (or similar) + walk-forward + `model_registry` champion/challenger |
| 6 | **Meta Model** | Learns agent reliability as a function of market state / asset / horizon / events — **not** fixed hand weights |

**Parallel policy (not a big stage):** document and eventually fix publication-time semantics for sparse macro/series before scaling fundamentals and ML.

**Future research (not implementation):** Market Regime / Market State — see [market-regime-v0-research.md](./market-regime-v0-research.md). Do **not** start Market Regime, Technical, Fundamentals, or ML implementation from this documentation task.

---

## Related docs

- [Analytics Feature Layer V1](./analytics-feature-layer.md)
- [ADR 0004 — Analytics Feature Store](./decisions/0004-analytics-feature-store-v1.md)
- [Relations Engine V1](./relations-engine-v1.md)
- [Future Learning Loop](./future-learning.md)
- [Modules](./modules.md)
- [Market Regime / Market State V0 Research](./market-regime-v0-research.md)
