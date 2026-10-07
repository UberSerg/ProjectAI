# Kraken Intelligence Stack V1 — Architecture Contract

**Status:** ACTIVE implementation contract  
**Product release:** not in this PR (post–Kraken 1.04; no 1.05 here)  
**Technical VERSION:** remains `1.0.0`  
**Isolation:** RESEARCH / ADVISORY only — no Candidate promotion, no Shadow switch, no Daily Decision switch, no broker execution.

## Product goal

Give OWNER a coherent company intelligence view: independent analytical models, transparent disagreement, deterministic committee, evidence + provenance, explicit UNKNOWN/ABSTAIN.

## Non-negotiable invariants

- Instrument Master ≠ Research Universe
- Prediction ≠ Policy ≠ Risk ≠ Execution
- `period_end` ≠ `known_at`; `published_at` ≠ `observed_at` ≠ `known_at`
- Missing ≠ zero; Unknown > fabricated
- Cash first-class; EOD → next OPEN research execution contract
- No HFT / ticks / order book history
- No paid data, captcha bypass, ToS circumvention
- No fabricated historical news timestamps / document backdating
- LLM numbers are not numerical truth without source provenance
- No hidden chain-of-thought storage
- ACTIVE DatasetSpec unchanged; Candidate V0/V1 pins unchanged
- Canonical Evidence Campaign V1 dossiers remain immutable

## Module root

```text
backend/app/modules/intelligence/
```

Subpackages by agent ownership (see `docs/intelligence/AGENT_OWNERSHIP.md`).

## Universal time / provenance

Every external information item distinguishes:

| Field | Meaning |
|-------|---------|
| `source_published_at` | Publisher's claimed publication time |
| `observed_at` | When Kraken first observed the artifact |
| `known_at` | Earliest time Kraken may treat as decision-available (`max` of authoritative release and honest observed, per provider policy) |
| `effective_at` / `period_end` | Economic/reporting effective date when applicable |
| `ingested_at` | Persistence timestamp |

A model evaluating `as_of` **must not** see items with `known_at > as_of`.

## SignalOutputV1

Canonical output of every independent analytical model. See `contracts/signal.py`.

States: `POSITIVE | NEUTRAL | NEGATIVE | ABSTAIN | UNKNOWN`.

No action/order objects. No prose-only outputs.

## CommitteeDecisionV1

First layer allowed to combine independent `SignalOutputV1` + knowledge rules + risk.  
Advisory: `CONSIDER_INCREASE | HOLD | CONSIDER_REDUCE | ABSTAIN`.  
Disagreement is preserved, not averaged away.

## IntelligenceSnapshotV1

Aggregate OWNER-facing payload for one instrument at `as_of`.

## Persistence

- Schema: `intelligence` (additive)
- Reuse `market.candles` with `timeframe` (e.g. `60m`) when semantically safe
- Reuse existing fundamentals FNS infrastructure; do not rewrite
- Raw external documents: append-only / immutable content_hash; corrections = new revisions
- Prefer one consolidated migration for stack tables

## Research

New intelligence feature packs use a **new** research experiment identity.  
Do not retune V4 / Canonical Campaign after seeing results.  
Prospective-only packs are valid when historical `known_at` cannot be established.

## Production isolation checklist

- `PIT_DAILY_CORE_ACTIVE_VERSION` unchanged
- Candidate V0/V1 `dataset_spec_version` unchanged
- `persist_registry=false` for research intelligence paths
- No Shadow / Daily Decision / PersonalOperation / broker mutations from intelligence refresh
