# ProjectAI Future Intelligence Roadmap

## Status

**Status: Living roadmap**

This document describes **direction**, not shipped capability. Sections marked Implemented
are grounded in code; everything else is planned / research unless an explicit stage begins.

Related research: [Market Regime / Market State V0 Research](./market-regime-v0-research.md).  
Learning / Decision Memory / Candidate–Champion: [Future Learning Loop](./future-learning.md).

---

## Product direction (Kraken)

ProjectAI is not only a stack of analytical agents. The long-term goal is a
**self-learning investment system** that must prove itself on historical data and in
virtual environments **before** it earns access to real execution.

**Kraken** is the internal name for that mature state. It is **not** a module, package,
namespace, or class — do not invent `modules/kraken` because this document mentions it.

Architectural path to real money (conceptual):

```text
Historical Simulation
  → Walk-forward validation
  → Shadow / Paper Portfolio
  → Signal Mode
  → Human-confirmed Broker Execution
  → Small real capital
  → Limited Autonomous Trading
```

Broker connectivity appears only as an **Execution Adapter**. Prediction / Policy / Risk
must not be rewritten for each broker.

---

## Target pipeline (direction)

Not all of this exists. Do not implement unused stages from this diagram.

```text
Market Data
    ↓
Analytics / Feature Layer
    ↓
Relations
    ↓
Technical / Fundamental / other intelligence
    ↓
Point-In-Time Dataset
    ↓
Prediction Models
    ↓
Meta Model
    ↓
Trading Policy
    ↓
Risk Manager
    ↓
Order Intent
    ↓
Execution Adapter
        ├ Historical Simulator
        ├ Paper / Shadow Portfolio
        └ Real Broker Adapter
    ↓
Portfolio / Trades / Outcomes
    ↓
Learning / Evaluation / Retraining
    ↓
Decision Memory
```

**Current Dataset/PIT V0 subset (Phase 1–3 accepted; not the full diagram above):**

Analytics + Technical features + Technical signal + Relations as-of → forward labels
(`1/5/10/20` obs). Fundamentals, regime, Meta Model, Policy, Risk, Simulator, and broker
are not part of Dataset/PIT V0.

**Role separation (invariant):**

| Layer | Responsibility |
|-------|----------------|
| Prediction Models | Forecast market / outcomes |
| Meta Model | Relative usefulness / trust in agents & models |
| Trading Policy | Desired action |
| Risk Manager | Shrink, constrain, or reject |
| Execution Adapter | Execute Order Intent only |

---

## Current foundation (grounded)

```text
Market Data V1                 Implemented
        ↓
Analytics Feature Layer V1     Implemented  (basic_daily, PIT, quality)
        ↓
Relations Engine V1            Implemented  (as_of snapshots)
        ↓
Technical Agent V1             Implemented  (technical_daily + rules_v1)
        ↓
Dataset / PIT Join V0          Phase 1 + 2 implemented; Phase 3 acceptance completed
```

| Layer | Role | Status |
|-------|------|--------|
| Market Data | Candles, series, DQ issues | Implemented |
| Analytics | Versioned derived daily features | Implemented (ADR 0004) |
| Relations V1 | Statistical relations with `as_of_date` | Implemented |
| Technical Agent V1 | Technical features + pure `rules_v1` signals | Implemented |
| Dataset / PIT V0 | Honest `X(t)` + forward labels `Y` | **Phase 1 + 2 implemented; Phase 3 acceptance completed** (UI / Parquet / ML not in V0) |

**Domain ports today:** `TechnicalModel`, `PortfolioPolicy`, `LLMProvider`;
`learning.model_registry` foundation (no training loop yet).

**Explicitly not implemented:** Fundamental Intelligence, Market Regime, Prediction ML training,
Meta Model, Trading Policy / Risk / Order Intent, Simulator, Broker adapter, Recommendations / BUY-SELL,
autonomous real trading.

---

## Dataset / PIT Join V0 — current status

### Goal

Prove that historical layers can be joined into an ML-ready row without look-ahead:

```text
X(t) = information known <= t
Y(t, N) = future return after t   (LABEL only)
```

### Phase 1 (implemented)

- `learning.dataset_specs`, `dataset_runs`, `dataset_samples_daily` (migration `20260901_0009`)
- seed `pit_daily_core` v1 with explicit feature/label/metadata manifest
- typed contracts; forward labels `1/5/10/20` trading observations
- PIT validator; Analytics + Technical features + Technical signal join
- version pins; deterministic sample/dataset hashes
- API + Celery `dataset_build`; diagnostics section

### Phase 2 (implemented)

- Relations as-of join (latest `snapshot.as_of <= t`, max age 8 calendar days)
- self / missing / stale / invalid → NULL, not 0
- Relations optional for training eligibility
- coverage by context (IMOEX, USD_RUB, CNY_RUB, KEY_RATE)

### Phase 3 (acceptance completed)

End-to-end DatasetBuild on current universe (`2024-01-01` → latest candles), smoke +
repeat-build hashes, SBER/latest/PLZL audits, run summary API, seed freeze after first
SUCCESS, watchdog `scripts/accept-dataset-pit.ps1`.

**Still out of Dataset/PIT V0 (do not treat as done):**

- UI / Datasets page
- Parquet export
- Prediction ML / CatBoost / XGBoost
- Simulator, Trading Policy, Risk, Broker
- Fundamentals, Market Regime, History Expansion
- dedicated `dataset-pit-v0.md` (not required for V0 close)

---

## Technical Agent V1 (implemented)

See [technical-agent-v1.md](./technical-agent-v1.md).

Summary: pure `TechnicalModel`; service loads PIT Analytics + technical features; `rules_v1`
is a heuristic baseline (not alpha). Relations are **not** inside rules_v1 by design.

---

## Fundamental Intelligence (planned)

Corporate reports ≠ RSS news sentiment. Prefer a dedicated **`fundamentals`** contour in
Core DB (today’s module folder may still say `news` — rename when the stage starts).

```text
Corporate Reports → Raw filing → Parser (+ optional LLM assist)
  → Structured Financial Facts → Derived features → Event Study / ML / Expert (optional)
```

**Expert** (optional): LLM-assisted research, narrative interpretation, or explanation —
**not** an online decision engine and not a substitute for Trading Policy / Risk / Execution.

**Critical PIT:** `period_end ≠ published_at`. A model may use a report only after actual
publication. Consensus needs its own historical snapshots / timestamps.

**Event study** (design): event at `t` → returns `t+1` / `t+3` / `t+5` / `t+10` / `t+20`.
Complementary to continuous Relations — not a substitute.

LLM may help extract/classify text. Numbers, dates, and `published_at` are never truth
solely because an LLM said so — validated structured facts live in Core.

---

## Market Regime / Market State (research)

See [market-regime-v0-research.md](./market-regime-v0-research.md).

Prefer a rich PIT **state vector** (trend, volatility, breadth, correlation concentration,
liquidity/FX/rates/commodity pressure, …). Optional coarse regime label is allowed.

**Critical:** `regime_detected_at_t ≠` ex-post regime label. Do not backfill “this was already
a crisis” onto days when that could not yet be known.

---

## Market History Expansion (planned)

Current depth (~2024–present) is enough for early validation / smoke, **not** enough for
serious Kraken training.

Plan: expand toward roughly **2014 → present** (or deeper if source quality allows).

Deep history introduces PIT / DQ risks that are **not** solved today:

- splits, denominations, ticker changes, delistings, corporate actions
- survivorship bias; historical universe composition
- macro publication timestamps

Current active universe on deep history would still carry survivorship bias until a PIT
universe history exists.

---

## Prediction ML / Meta / Trading stack (later)

After honest datasets:

1. **Prediction ML Candidate** — CatBoost/LightGBM/XGBoost (or similar) on PIT `X → Y`;
   walk-forward; versioned artifacts. **Before Historical Simulator exists, this stage is
   offline prediction evaluation only** (metrics on unseen future label windows). It is **not**
   trading validation, portfolio PnL, or policy proof.
2. **Historical Simulator V0** — same decision pipeline; costs, slippage, delay; many
   experimental lives. **Trading / PnL / policy validation starts here**, once Simulator plus
   Trading Policy and Risk Manager exist. Warning: 10 000 runs on one known period ≠ 10 000
   independent markets.
3. **Trading Policy + Risk Manager + Order Intent** — separate from prediction.
4. **Learning loop / Candidate–Champion / Meta Model / Market State** — see
   [future-learning.md](./future-learning.md).
5. **Shadow / Signal / Broker adapter / limited real trading** — only after earned gates.

Core numerical loop should not require LLM tokens. Polza remains for language layers.

---

## ML-ready architecture (contract)

```text
state @ t
+ analytics @ t
+ relations @ t
+ technical @ t
+ fundamentals known @ t
+ market regime @ t
        ↓
target return t+N   (LABEL)
```

**Hard rule:** `X` uses only information `<= t`. Labels use the future strictly after `t`
and live **outside** the feature row.

Version pins on every dataset / model card: feature sets, relation sets, technical model,
fundamental publish policy, regime model, dataset code/version, label formula, quality policy,
source watermarks.

Known look-ahead holes (still open): sparse series without true `published_at`; unadjusted
prices / corporate actions; Relations `best_lag` as ML feature; mutating semantics without
version bump; confusing backward `return_*` with forward labels.

---

## Risks / architectural traps

1. Technical Agent as a second unversioned feature store  
2. Live Relations recompute treated as historical  
3. `best_lag` / exploratory lead-lag without PIT constraint  
4. Fundamentals keyed by `period_end` instead of `published_at`  
5. LLM as source of financial numbers or dates  
6. Mixing adjusted and unadjusted prices silently  
7. Mutating feature / relation / dataset semantics without version bump  
8. Premature Simulator / broker / RL / microservices / new DBs  
9. Collapsing Prediction + Policy + Risk + Execution into one “agent”  
10. Treating repeated in-sample simulations as independent experience  

---

## Recommended sequence

Roadmap, **not** a rigid implementation order. May change after earlier stage results.
Do not start a stage from documentation alone.

| # | Stage | Status / intent |
|---|--------|-----------------|
| — | Market Data / Analytics / Relations / Technical | **Implemented** |
| 1 | **Dataset / PIT Join V0** | Phase 1 + 2 implemented; Phase 3 acceptance completed (no UI / no ML) |
| 2 | Dataset hardening / later layers | UI, Parquet, History Expansion — not part of V0 close |
| 3 | **Market History Expansion** (+ DQ / corporate-actions awareness) | Depth for serious training |
| 4 | **Fundamental Intelligence V1** and/or **Prediction ML Candidate V0** | Order depends on data readiness; ML Candidate = **offline prediction metrics only** until Simulator + Policy/Risk (stages 5–6) |
| 5 | **Historical Simulator V0** | Walk-forward **trading / policy / PnL** evaluation of candidates |
| 6 | Trading Policy + Risk + Portfolio simulation | Decision stack without real broker |
| 7 | Learning loop / Candidate–Champion / Meta Model / Market State | Durable learning |
| 8 | Shadow / Signal / Broker Execution Adapter / limited real capital | Earn the right to trade |

**Parallel research (not auto-implementation):** Market Regime / Market State; publication-time
semantics for sparse macro/series; adjusted-price / corporate-actions pipeline.

---

## Related docs

- [Architecture Overview](./overview.md)
- [Analytics Feature Layer V1](./analytics-feature-layer.md)
- [Relations Engine V1](./relations-engine-v1.md)
- [Technical Agent V1](./technical-agent-v1.md)
- [Future Learning Loop](./future-learning.md)
- [Market Regime / Market State V0 Research](./market-regime-v0-research.md)
- [Modules](./modules.md)
- [Data Storage](./data-storage.md)
- [ADR 0004 — Analytics Feature Store](./decisions/0004-analytics-feature-store-v1.md)
