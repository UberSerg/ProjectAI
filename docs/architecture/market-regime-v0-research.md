# Market Regime / Market State V0 Research

## Status

**Research / Not implemented**

This document is architectural research only. It does **not** authorize migrations, tables, APIs, dependencies, or code.

Relations Engine V1 and Technical Agent V1 are already implemented. Market Regime / Market State
still must **not** start automatically — begin only when an explicit stage requests it, preferably
after Dataset/PIT discipline is solid enough to catch leakage.

Parent roadmap: [Future Intelligence Roadmap](./future-intelligence-roadmap.md).

---

## Purpose

Investigate how ProjectAI can answer:

> “In what **state** is the market **now**?”

Goals:

- Go beyond crude fixed labels (`bull` / `bear`).
- Prefer a **rich, machine-readable continuous state vector**.
- Keep detection **point-in-time safe** for ML and backtests.
- Enable later **Relations × regime** conditioning and **Meta Model** agent reliability as a function of market state.
- Let LLM/Polza **translate** structured state to natural language later — **never compute** the state itself.

Non-goals for this research:

- Implementing detectors, installing libraries (`ruptures`, etc.), writing code, or creating tables.
- Replacing Relations Engine V1 or changing its current schema mid-flight beyond what V1 already plans to store.

---

## What is Market State

**Market State** is a structured representation of market conditions at calendar/trading date `t`, assembled only from information available ≤ `t`.

It is closer to an operational “feel of the market” than to a single price print:

```text
Not only:  “IMOEX −1.2% today”

But:       volatility rising
           correlations concentrating
           FX pressure increasing
           breadth weakening
           rate-sensitive names underperforming
           historical lead/lag relationships deteriorating
           market entering a transition / change-point region
```

Conceptual layers:

| Layer | Meaning |
|-------|---------|
| Continuous state vector | Primary ML/agent input — measurable scalars/z-scores |
| Optional categorical regime label | Coarse tag for UI / conditioning (risk-off, trend, etc.) |
| Transition / change-point flags | “Behavior unlike recent history” |
| Provenance | Model version, source feature/relation sets, watermarks |

LLM later: narrative overlay. Deterministic/statistical code: sole authority for numbers.

---

## Candidate Input Features

### From Analytics (available foundation)

- Returns: `log_return_1d`, multi-horizon `return_*`
- Volatility: `volatility_5d`, `volatility_20d` (and ratios / changes)
- Drawdown: `drawdown_20d` (index and single names)
- Volume: `volume_change_1d`, `volume_zscore_20d`
- Quality: exclude or down-weight `price_discontinuity` / invalid rows

Index / cross-section (future aggregates over universe, not all implemented):

- breadth proxies (advance/decline, % above SMA — needs definition stage)
- dispersion of returns / vols across liquid names

### From Relations (V1 — implemented; historical coverage may still be limited)

- Correlation strength at fixed windows (20/60/120) and methods (pearson/spearman)
- Relation stability (V1 `stability_subwindow` metrics where stored)
- Correlation concentration (e.g. average |corr| of liquid pairs; PCA/factor share of corr matrix — derived later)
- Lead/lag structure at **fixed** lags 1..5 (not ex-post “best lag” alone)
- Breakdown: large drop in |corr| or stability vs own history (change-point on relation series)

### Macro / series (Market + Analytics as-of)

- FX pressure (USD_RUB and peers pct_change / z-scores)
- Rate pressure (KEY_RATE, RUONIA absolute changes / levels)
- Index pressure (IMOEX / sector indices returns and vols)
- Commodities later (oil, metals) as series exist

### From Technical (future)

- Trend / momentum factors (SMA distance, RSI region)
- Volatility factors (ATR/close)
- Used as **inputs to state**, not as BUY/SELL

### Fundamental / news (future only)

- Earnings calendar density, surprise aggregates, guidance shocks
- Event-study intensity around filings
- Not required for Market State V0

---

## Candidate Approaches

Comparison summary for ProjectAI (modular monolith, Docker-first, PIT-first, explainability valued):

| Approach | Fit for early V0 | Notes |
|----------|------------------|--------|
| Deterministic rules | **Best starting point** | Transparent, easy PIT, cheap ops |
| Clustering | Useful V0.5 / V1 | Labels emerge; need careful online assignment |
| HMM | Later | Powerful; harder explainability & PIT training discipline |
| Change-point detection | **Important companion** | Detects “stopped behaving like before” |
| Mixture models | Later | Overlaps clustering/HMM |
| Supervised classification | Only with careful labels | Needs hand or ex-post labels → leakage risk |

Do **not** pick the most complex method because it looks smarter.

---

## Deterministic Rules

**Idea:** thresholds and transforms on PIT features → continuous scores and optional coarse tags.

**Examples:**

- `vol_regime = volatility_20d / median(volatility_20d, lookback≤t)`
- `trend_strength = return_20d / volatility_20d`
- `fx_pressure = zscore(USD_RUB pct_change, window≤t)`
- `corr_concentration = mean(|corr|) over liquid pairs @ as_of_t`

**Pros:** explainable; trivial unit tests; natural PIT if windows are backward-only; low ops cost.

**Cons:** brittle thresholds; misses nonlinear regime structure; many free parameters.

**Explainability:** excellent.

**PIT:** strong if all inputs are as-of and no future calibration of thresholds on the full sample (calibrate on past-only or freeze rule version).

**Data needs:** Analytics (+ Relations snapshots for concentration).

**Sensitivity:** medium (threshold choice).

**Ops complexity:** low.

**V0/V1:** **primary recommendation for V0**.

---

## Clustering

**Idea:** cluster historical state vectors (k-means, GMM, hierarchical) into K regimes; assign today’s vector to nearest cluster using a model fit only on data ≤ t (or frozen walk-forward fits).

**Pros:** discovers structure without hand labels; continuous distances to centroids useful.

**Cons:** cluster identity can permute across refits; online/PIT assignment must freeze cluster definitions per model version; sensitive to scaling/features.

**Explainability:** medium (centroid profiles).

**PIT:** medium–hard — naive full-sample clustering then back-labeling = leakage. Need versioned fits + as_of assignment.

**Data needs:** multi-year daily state vectors.

**Sensitivity:** high to K and feature set.

**Ops complexity:** medium (retrain cadence, version pins).

**V0/V1:** optional after continuous vector exists; not required on day one.

---

## HMM

**Idea:** Hidden Markov Model on returns/vols/state vector; latent states + transition matrix.

**Pros:** explicit regime persistence and transition probabilities; classic in quant literature.

**Cons:** assumption-heavy; local optima; hard to explain to product owners; easy to leak if smoothed with future observations (two-filter / Viterbi on full path).

**Explainability:** poor–medium.

**PIT:** use **filtered** (causal) state probabilities only; ban full-sample smoothed states in ML features.

**Data needs:** long clean series; careful handling of discontinuities.

**Sensitivity:** high.

**Ops complexity:** high.

**V0/V1:** defer past V0; consider only after Dataset/PIT discipline exists.

---

## Change-Point Detection

ProjectAI should notice: **“the market stopped behaving as it did.”**

Example: SBER↔IMOEX correlation historically stable, then abruptly breaks.

### Approaches (analysis only — no installs, no code)

#### Rolling structural-break heuristics

- Rolling mean/variance of returns or of a relation metric; flag when latest window differs from prior baseline by z-score / CUSUM-like cumulative sum of residuals.
- Relation-specific: `|corr_60(t) − median(corr_60[t−L:t−1])|` large and persistent.

**Pros:** simple; PIT-friendly; aligns with Relations snapshots.

**Cons:** laggy; many false positives in noisy markets.

**V0:** **recommended companion** to deterministic state vector.

#### CUSUM / Page-Hinkley style

- Cumulative sum of deviations from a target mean; alarm when threshold crossed; optionally reset.

**Pros:** well-understood online detection; causal.

**Cons:** needs careful thresholding; sensitive to variance changes (may need adaptive CUSUM).

**V0/V1:** good candidate for “transition flag” features without heavy deps.

#### Library-class methods (e.g. `ruptures`-style)

- Offline optimal segmentation (PELT, BinSeg, BottomUp) on a cost function over returns/corr series.

**Pros:** statistically strong segmentation for research notebooks.

**Cons:** classic offline algorithms see the **whole** series → **ex-post** change times. Using those labels in historical ML = leakage unless reformulated as online/causal detection with delay modeling.

**V0:** use only for **research labeling studies**, not as default ML features. If ever productionized, wrap as: detect at `t` with data ≤ `t`, store `detected_at`, optional `estimated_change_start` as **metadata not used as feature** unless delayed-awareness is modeled.

#### Bayesian change-point

- Posterior over run length / change probability (e.g. online Bayesian changepoint detection).

**Pros:** probabilistic “hazard” of change; natural continuous feature.

**Cons:** heavier math/ops; prior sensitivity; still must freeze causal filtering.

**V0:** defer; interesting V1+ research.

### Change-point summary for ProjectAI

| Method | Production V0? | Role |
|--------|----------------|------|
| Rolling heuristics on Analytics + Relations series | Yes (design) | Transition / breakdown flags |
| Online CUSUM-like | Yes (design) | Same |
| Offline ruptures-style segmentation | Research only | Ex-post analysis |
| Bayesian online CPD | Later | Probabilistic transition |

---

## Other Approaches

### Mixture models

Continuous latent mixture over returns — overlaps clustering/HMM. Defer.

### Supervised regime classification

Train on hand labels or crisis calendars. Risky: labels often defined with hindsight. Only if labels are timestamped as “known at t” (e.g. official announcements with `published_at`).

### Dimensionality reduction

PCA / factor share of cross-sectional returns or corr matrices → continuous “concentration” / “factor dominance” features. Attractive for V0.5 once universe definition is stable.

### Expert / LLM classification

**Rejected** as state computer. Allowed later as narrative over stored vector.

---

## Point-in-Time Requirements

**Critical distinction:**

| Concept | Meaning | Safe for ML X? |
|---------|---------|----------------|
| `regime_detected_at_t` | What the system could output using only data ≤ t | **Yes** |
| `regime_labeled_ex_post` | After the fact, algorithm decides crisis started a week earlier and backfills “crisis” on those days | **No** — leakage |

Bad pattern:

```text
After crisis, detector realizes crisis began 7 days ago
→ historical dataset labeled “crisis” for that entire week
→ model “predicts” crisis using features that effectively peeked
```

Required practices:

1. Persist **detection time** (`as_of_date` / `calculated_at` semantics aligned with trading calendar).
2. If model estimates `change_start < as_of`, store it as diagnostic only; ML features use state **as known at as_of**.
3. Freeze `model_code` / `model_version`; never silently rewrite historical snapshots.
4. Walk-forward refits produce **new** versions; old snapshots remain immutable.
5. Ban full-sample HMM smoothing / offline segmentation labels in training features.

Market State for ML = **what the system could have known on date t**.

---

## Proposed Historical Representation

Conceptual only — **do not create tables now**.

```text
market_state_runs
  - run_id, workflow, model_code, model_version
  - source_feature_set / source_relation_set refs
  - source_watermark
  - status, started_at, finished_at

market_state_snapshots
  - as_of_date
  - model_code, model_version
  - state_vector          (JSONB or typed columns)
  - regime_label          (nullable)
  - regime_probabilities  (nullable JSONB)
  - transition_flags      (nullable)
  - source_feature_set
  - source_relation_set
  - source_watermark
  - quality_flags
  - calculated_at
```

Emphasize storing the **continuous state vector**, not only a label. Labels are optional projections.

Mirror patterns already used by Analytics (`feature_runs`) and Relations (`relation` runs/snapshots with `as_of_date`).

---

## Continuous State vs Regime Label

| | Continuous vector | Categorical label |
|--|-------------------|-------------------|
| ML / Meta Model | Preferred primary input | Optional conditioner / stratification |
| UI | Needs translation / sparklines | Easy badge |
| Leakage surface | Lower if PIT | Higher if ex-post taxonomy |
| Early V0 | **Ship this first** | Can wait |

**Recommendation:** V0 stores continuous variables (+ optional simple rule-based tags for UI). Do not block V0 on a perfect bull/bear/sideways taxonomy.

---

## Relations Integration

### Hypothesis

Asset relations **depend on market state**.

Example:

```text
SBER ↔ IMOEX
  normal:   corr ≈ +0.35
  risk-off: corr ≈ +0.85
```

Other pairs may **break** under stress. Future work: relation behavior **conditioned on regime**, and stability **by regime**.

### What Relations V1 should already store (no redesign mid-flight)

So later regime conditioning can use history **without inventing past**:

| Already in V1 design | Why it matters for regime |
|----------------------|---------------------------|
| `relation_snapshots` keyed by **`as_of_date`** | Time series of market structure known at t |
| Versioned `relation_sets` + parameters in JSON | Replay / pin semantics |
| Multiple **windows** (20/60/120) | Short vs long structure; breakdown across horizons |
| Pearson + Spearman | Robustness checks |
| Lead-lag metrics for **both directions**, lags 1..5 | Structure of leadership under stress |
| Stability-related metrics (per set parameters) | Early “relation breakdown” signals |
| Quality / coverage / discontinuity exclusions | Avoid fake breaks from bad prints |
| Runs / watermarks | Provenance for dataset pins |

**Do not require now:** regime-conditioned correlation tables, Granger, or online change-point jobs inside Relations V1.

**Later (after snapshots exist):** join `relation_* @ as_of` with `market_state @ as_of`; estimate corr distributions by state buckets; never backfill conditioned metrics as if they existed historically without an as_of model version.

Exploratory `best_lag` remains a **diagnostic**, not a default ML feature unless chosen on past-only windows ≤ t.

---

## Technical Agent Integration

- Technical factors (trend, momentum, vol) can **feed** Market State.
- Market State can **condition** interpretation of Technical scores (e.g. trend-following more reliable in high `trend_strength` / low transition risk).
- Keep boundaries: TechnicalModel stays **pure**; state assembly is a separate service (same pattern as TechnicalSignalService).
- Do not fold full regime engine into Technical Agent V1.

---

## Fundamental Integration

- V0 Market State does **not** need fundamentals.
- Later: event density, surprise aggregates, post-earnings drift regimes as **additional state dimensions** or event context for Meta Model.
- Event Study (see roadmap) interacts with state: “same EBITDA surprise, different vol/corr regimes → different return paths.”
- Always gate on `published_at`.

---

## Meta Model Integration

Meta Model should **not** use fixed hand weights:

```text
Technical 30% + Relations 30% + Fundamental 40%   ← rejected as primary design
```

Instead learn statistically:

```text
agent_reliability ≈ f(
  market_state_vector @ t,
  asset / sector,
  horizon,
  volatility,
  event_context
)
```

Examples:

- Technical Agent stronger in trend / low-transition states
- Relations / macro factors stronger in FX/rate-pressure states
- Fundamental Agent more useful around earnings events

Market State is a first-class Meta Model input; categorical regime is optional stratification.

---

## Leakage Risks

1. Ex-post regime backfill (`regime_labeled_ex_post` on days before detection).
2. Offline change-point / full-sample HMM smoothing used as historical features.
3. Clustering fit on full history then assigned backward without versioned causal assignment.
4. Thresholds / PCA loadings calibrated on the full sample including future.
5. Using Relations `best_lag` chosen with future windows.
6. Fundamentals or macro with observation date ≪ true `published_at`.
7. Recomputing state “today” and overwriting historical snapshots.
8. Target returns accidentally included in state vector construction.

---

## Recommended V0

**Minimal Market State V0 = continuous vector first; categorical label optional/lightweight.**

Suggested **8 continuous variables** (illustrative names):

1. `equity_trend_strength` — index `return_20d / volatility_20d` (IMOEX or defined universe proxy)
2. `equity_vol_level` — `volatility_20d` vs long backward median (z or ratio)
3. `equity_drawdown_depth` — index `drawdown_20d` (or longer once available)
4. `market_breadth_proxy` — % of liquid names with `return_20d > 0` (needs universe definition)
5. `corr_concentration` — mean |corr| of liquid equity pairs from Relations snapshot @ t (window 60)
6. `relation_stability_stress` — fraction of pairs with stability metric deteriorated vs own history ≤ t
7. `fx_pressure` — USD_RUB short-horizon z-score (as-of series)
8. `rate_pressure` — KEY_RATE / RUONIA change intensity (as-of)

Optional 9th–10th:

9. `volume_stress` — cross-sectional median `volume_zscore_20d`
10. `transition_score` — rolling/CUSUM-style break score on (vol, corr_concentration)

**Categorical label in V0?**

- **Not required** for ML readiness.
- Optional rule-based UI tag (e.g. `calm` / `trend` / `stress` / `transition`) derived from thresholds on the vector — stored nullable, versioned with the ruleset.
- Do **not** wait for HMM/clustering before shipping the vector.

**Method mix for V0:** deterministic transforms + simple online change-point / breakdown heuristics on Analytics + Relations snapshots. No new heavy ML libraries required for the research-approved V0 design.

---

## What Must Be Prepared Now

### Already sufficient

- Analytics Feature Layer V1: versioned daily features, no look-ahead calculators, quality flags, as-of series joins ([analytics-feature-layer.md](./analytics-feature-layer.md), ADR 0004).
- Relations V1 design: `as_of_date` snapshots, windows, lag metrics both ways, versioned sets, runs/watermarks ([relations-engine-v1.md](./relations-engine-v1.md)).
- Modular ports / learning registry foundation for later model versioning.
- Roadmap purity rule: models do not load DB; services assemble PIT inputs ([future-intelligence-roadmap.md](./future-intelligence-roadmap.md)).

### Cheap to add now

*(Documentation / discipline only — **no** production code required from this research task.)*

- Keep documenting: ML must use stored Relations snapshots, not live recompute.
- Keep `best_lag` as diagnostic vs PIT lag features in Relations docs (already a known trap).
- When Dataset/PIT V0 is designed, reserve columns for `market_state_model` / version pins (design note, not migration).
- Preserve universe / liquid-pair definitions as parameters (JSON), not hardcoded — when state needs breadth/corr concentration later.

Do **not** add regime tables, Celery jobs, or dependencies “just in case” during Relations V1.

### Can wait

- `market_state_runs` / `snapshots` tables
- HMM, Bayesian CPD, clustering production pipelines
- Regime-conditioned relation matrices
- Fundamental/news dimensions of state
- LLM narrative layer
- Meta Model reliability surfaces

---

## Recommended Implementation Stage

Place Market State **after** Relations V1 is stable enough to supply historical `as_of` snapshots, and preferably **after or alongside** Dataset/PIT Join V0 (so state joins are tested for leakage).

Suggested order (aligned with roadmap):

```text
Relations / Technical          (implemented)
  → Dataset / PIT Join V0      (accepted; v1 frozen)
  → Deep History H0–H6         (H0 contract only; H1+ not started)
  → Market State / Regime V0   ← continuous vector + snapshot store
  → Fundamentals V1 and/or ML Candidate / Simulator (order may vary)
  → Meta Model
```

Exact placement may move after Dataset/History results. **Do not start implementation from this document.**

---

## Open Questions

1. Canonical **universe** for breadth and corr concentration (IMOEX constituents? liquidity filter? fixed tickers list?)
2. Index proxy for “equity” state when multiple boards/indices exist
3. Trading calendar / session cut for `as_of_date` vs intraday later
4. How aggressive should transition flags be (precision vs recall)?
5. Should V0 persist only market-level state, or also sector / single-name state vectors?
6. Publication-time gaps for FX/rates — acceptable for V0 with documented limitation?
7. Whether optional UI regime labels should be multilingual product copy or stable machine enums
8. Interaction with corporate-action / unadjusted price limitations around state features
9. Minimum history length before first meaningful `corr_concentration`
10. Ownership: new `modules/` area vs under `analytics` / `relations` consumers

---

## Related docs

- [Future Intelligence Roadmap](./future-intelligence-roadmap.md)
- [Relations Engine V1](./relations-engine-v1.md)
- [Analytics Feature Layer V1](./analytics-feature-layer.md)
- [Future Learning Loop](./future-learning.md)
