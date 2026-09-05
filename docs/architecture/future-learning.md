# Future Learning Loop

## Status

**Planned / foundation only**

This document describes how ProjectAI is expected to learn over time. It is **not**
implemented end-to-end. For sequencing and Dataset/PIT status see
[future-intelligence-roadmap.md](./future-intelligence-roadmap.md).

Self-learning does **not** mean an LLM rewriting production prompts or code.

---

## Learning loop (target)

```text
New observations / outcomes
  → Training Dataset (versioned, PIT)
  → Train Candidate
  → Walk-forward / simulator evaluation
  → Candidate vs Champion
  → Approve / Reject / Rollback
  → Decision Memory snapshot
```

Foundation already includes:

- Core schema `learning` (model registry foundation; Dataset/PIT tables:
  `dataset_specs`, `dataset_runs`, `dataset_samples_daily`)
- `pit_daily_core` v1 (raw labels, frozen) and v2 (mechanical-price-return labels,
  deep history 2014→present on current cohort; frozen after first successful build;
  not auto-activated)
- `ModelRecord` / `ModelStatus` domain types (where present)
- Celery worker/scheduler for future jobs
- Separate Memory DB for Decision Memory (ADR 0002)

**Next learning step:** Trading Policy research on development OOS only (new holdout later);
Champion / dividends / historical universe still deferred.

Prediction ML Candidate V0 is **DONE** with research verdict **MIXED**
(`pit_daily_core` v2, `forward_return_20d`, CatBoost, expanding walk-forward, 2026 holdout).

**Prediction Candidate V1 Ranker** (research-only, in progress on
`feature/prediction-candidate-v1-ranker`): CatBoostRanker / YetiRank on the same Dataset V2
90-feature contract; output semantic `RANKING_SCORE` (relative attractiveness within a date,
not calibrated return %). Evaluated on **DEVELOPMENT_OOS only**. **No Forward activation.**
**No 2026 FINAL_HOLDOUT for model selection** (holdout already observed for V0). Does not
replace Candidate V0; live Forward/Shadow stay on V0 until a separate promotion decision.

Historical Simulator V0 is **IMPLEMENTED**: OOS-only predictions → RANK_LONG_ONLY_V0
(top 20% equal weight, weekly) → Risk guardrails → next-open historical fills → portfolio
ledger / metrics / IMOEX price-index benchmark. Explicitly **not** real execution; dividends
excluded; Trading Policy V0 is a simple diagnostic policy; Risk V0 is guardrails only.

**Simulator Dashboard V0** is **IMPLEMENTED** (research UI): runs list + run detail with NAV vs
IMOEX, drawdown, date inspector, fills/orders provenance, cost sensitivity. Not profitability
proof; not Champion; not real trading.

**Policy / Risk Research V1** (candidate research, not Champion):
- Prediction Candidate V0 / Dataset V2 unchanged (no retrain).
- Baseline `RANK_LONG_ONLY_V0` immutable.
- Policy candidate `RANK_HYSTERESIS_LONG_ONLY_V1` (entry top 20% / exit top 35%, equal weight,
  weekly, min trade weight delta 2pp) to reduce churn.
- Risk candidate `DRAWDOWN_GUARD_V1` (−20% → 50% gross; recover −10% → 100%).
- Compared on **DEVELOPMENT_OOS only**. Verdict: **POLICY_V1_PROMISING** (hysteresis).
  2026 FINAL_HOLDOUT was previously observed for V0 and is **not** pristine for Policy V1.
- No profitability claim; no promotion.

**Forward Signal V0** is **IMPLEMENTED / ACTIVE**: live PIT inference for latest completed
market date using frozen Candidate V0, exact 90-feature V2 pins, immutable `FORWARD_LIVE`
predictions from activation date forward.

**Shadow Portfolio V0** is **ACTIVE** (waiting for genuine future execution): two prospective
forward experiments (`SHADOW_HYSTERESIS_V1`, `SHADOW_HYSTERESIS_DD_V1`) consume immutable
Forward batches only. No backdated fills.

**Simulator Research Lab V0** is **IMPLEMENTED**: UI `/research` for manual DEV OOS
historical experiments (registered Candidate/Policy/Risk, costs, period), experiment
registry, comparison, cost-sensitivity family, FINAL_HOLDOUT launch protection.
Reuses Historical Simulator engine; no Candidate training; no Shadow/Forward mutation.

**Shadow / Live Research Dashboard V0** is **IMPLEMENTED**: UI route `/shadow` («Живой эксперимент»)
for prospective monitoring — pending-only start state is expected and correct.

**Daily Research Cycle V0** is **IMPLEMENTED** (schedule **DISABLED** by default): one operator/
Celery workflow advances Market→Analytics V2→Technical V2→Relations V2→Forward→Shadow→
Forward Outcome Evaluator without historical Forward/Shadow backfill.

**Forward Outcome Evaluator V0** is **IMPLEMENTED**: mature predictions after 20 future trading
observations using Dataset PIT V2 mechanical return semantics (no dividends).

Virtual / simulated portfolio first — no real broker trading in the MVP path.

---

## Walk-forward discipline

Historical evaluation must be walk-forward:

```text
train on past → trade/evaluate on unseen future → move forward
→ retrain only using information available at that moment
```

Example:

```text
2014–2017 train → 2018 test
2014–2018 train → 2019 test
…
```

A final out-of-sample window should remain untouched until final verification when feasible.

**Selection and tuning (no leakage):** feature selection, hyperparameter tuning, model
selection, policy tuning, and champion selection must use only information available **inside
the corresponding training window** for that walk-forward step. Do not tune or pick champions
using future folds, the final holdout, or full-sample hindsight. The final holdout stays
untouched until a deliberate final evaluation.

**Warning:** thousands of simulator runs on the **same known period** do not create thousands
of independent market experiences. They are useful stress/ablation experiments, not new history.

The same applies to Deep History: more daily rows are not more independent experience.
Adjacent samples are strongly dependent. History is loaded so Kraken can see **different
market regimes**, not to maximize row count. Walk-forward remains mandatory.

---

## Candidate → Champion

Future models and trading policies are not production by default:

```text
Candidate
  → backtest / walk-forward
  → comparison
  → Champion
  → shadow / live evaluation
  → promotion or rollback
```

Version models, datasets, policies, and evaluation metrics. Replay must be possible.

---

## Durable learning artifacts

Learning is stored through durable artifacts, not chat memory:

- datasets + feature/label manifests + hashes
- feature / relation / technical / fundamental versions
- model versions + config hashes
- policy / risk versions
- evaluation metrics
- agent reliability estimates
- market state / regime snapshots (when they exist)
- trade outcomes / PnL / drawdown
- Decision Memory reviews / lessons

---

## Decision Memory

Separate physical PostgreSQL + **pgvector** (not Core OLTP).

Future immutable snapshots may include:

- Decision
- Prediction
- Model / feature / dataset versions
- Market state
- Agent outputs
- Portfolio state
- Trading Policy decision
- Risk decision
- Order Intent
- Execution / costs
- Outcome / PnL / drawdown
- Evaluation
- Review / lesson
- Embeddings where useful

**Rules:**

- Do not rewrite the original decision after the outcome arrives (decision ≠ subsequent review).
- Decision Memory does **not** replace ordinary ML datasets / feature stores.
- Embeddings and decision narratives stay out of analytics feature tables.

See ADR 0002 and [data-storage.md](./data-storage.md).

---

## Simulator role (future)

A Historical Simulator should eventually support many experimental “lives”:

- time windows and regimes
- starting capital, commissions, slippage, execution delay
- universes, models, policy/risk parameters
- ablation of individual agents

Same Prediction → Policy → Risk → Order Intent path; only the Execution Adapter changes
(Simulator vs Paper vs Broker).

---

## LLM boundary

Core numerical learning and trading decisions should run without mandatory LLM spend.
Polza/LLM may assist research, explanation, and text extraction — never as calculator or
sole source of truth for numbers, dates, or publication times.
