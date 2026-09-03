# Modules

Module folders under `backend/app/modules/` are intentional boundaries.

| Module | Responsibility (current / planned) |
|--------|-------------------------------------|
| market | Market data access, ingestion, DQ; RAW candles as source of truth.
  Corporate actions are **events** (H1: MOEX `SPLIT` ingest). H2: source validity windows. |
| analytics | Feature sets, calculators, feature runs |
| relations | Relations Engine V1 (inputs, snapshots, lags) |
| technical | Technical Agent V1 (`technical_daily`, rules_v1 signals) |
| learning | Dataset/PIT builder, future ML registry / training jobs |
| news | Placeholder for news/fundamental analysis (future `fundamentals` contour) |
| risk | Future Risk Manager |
| recommendations | Future Meta / recommendation presentation (not BUY-SELL today) |
| portfolio | Future virtual / paper portfolio |
| memory | Decision Memory application API (Memory DB) |
| workflows | Orchestration helpers for background pipelines |

Status of analytical layers is tracked in [future-intelligence-roadmap.md](./future-intelligence-roadmap.md).
Do not implement empty future modules “for completeness”.

Ports for swappable implementations live in `domain/ports`:

- `TechnicalModel` + `TechnicalModelInput` / `TechnicalModelOutput`
- `PortfolioPolicy` + `PortfolioPolicyInput` / `PortfolioPolicyOutput`
- `LLMProvider` + `LLMMessage` / `LLMResponse`

Contracts use typed domain DTOs (not open `dict[str, Any]` for primary inputs/outputs).
Optional `metadata` fields remain a narrow JSON-scalar mapping for extensibility.

**Purity reminder:** models behind ports do not load the database; application services
assemble point-in-time frozen inputs.
