# Portfolio Candidate Orchestration V1

```text
Market / Models / Fixed Income
        ↓
Opportunity + Confidence
        ↓
CBR Hurdle
        ↓
Asset Allocation (InvestmentDecisionEngine)
        ↓
Portfolio Risk Gate
        ↓
Realistic Lot Allocator
        ↓
Portfolio Candidate (PORTFOLIO_CANDIDATE_V1)
        ↓
Investor Cockpit UI
```

## Entry points

- Application: `portfolio_candidate_service.build_portfolio_candidate`
- Domain types: `portfolio_candidate.py`
- API:
  - `POST /api/v1/portfolio/candidate/preview`
  - `POST /api/v1/portfolio/candidate/snapshots`
  - `GET /api/v1/portfolio/candidate/current`
  - `GET /api/v1/portfolio/candidate/history`
  - `GET /api/v1/portfolio/candidate/{id}`
  - `GET /api/v1/portfolio/candidate/{id}/diff`

## Persistence

Migration `20260907_0020` → `investment.portfolio_candidates`.

Snapshots are append-only. Payload is the source of replay.

## Safety

- Do not invent synthetic positions when data is missing.
- Do not force 100% investment.
- Do not auto-switch blocked equity into 100% bonds.
- Do not mutate Prediction / Calibration / Forward / Shadow rules.
