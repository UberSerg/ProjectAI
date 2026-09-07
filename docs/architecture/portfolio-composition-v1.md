# Portfolio Composition V1 — Architecture

```text
Opportunity + Confidence
        ↓
Asset Allocation (sleeve targets)
        ↓
EQUITY_COMPOSITION_V1 / FIXED_INCOME_COMPOSITION_V1
        ↓
Per-instrument Portfolio Risk Gate
        ↓
Integer lot allocator (dirty price for bonds)
        ↓
Final risk validation (actual weights)
        ↓
CONCRETE_PORTFOLIO_CANDIDATE_V1 → Investor Cockpit
```

## Modules

- `domain/composition_config.py` — typed operational limits
- `domain/equity_composition.py` — deterministic equity selection
- `domain/fixed_income_composition.py` — data-quality FI selection
- `application/portfolio_composition_service.py` — load signals/bonds + pre/post gate
- `application/portfolio_candidate_service.py` — orchestration + snapshots

## Equity

Uses latest SUCCESS forward batch (active model, no silent V0↔V1 switch).
Semantic preserved (`EXPECTED_RETURN` vs `RANKING_SCORE`).

## Fixed Income

RUB bonds with market snapshot. Prefer SUPPORTED + Government for research.
Dirty purchase = clean% × nominal + NKD.

## Safety

No forced investment. No fake FI fallback. No retrospective prospective history.
