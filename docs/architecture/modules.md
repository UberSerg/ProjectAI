# Modules

Module folders under `backend/app/modules/` are intentional boundaries:

| Module | Future responsibility |
|--------|------------------------|
| market | market data access |
| relations | dependency/correlation engine (Relations Engine V1) |
| technical | technical analysis |
| news | news/fundamental analysis |
| risk | risk analysis |
| recommendations | meta-model outputs |
| portfolio | virtual portfolio manager |
| learning | datasets, champion/challenger |
| memory | Decision Memory application API |
| workflows | orchestration of background pipelines |

Ports for swappable implementations live in `domain/ports`:

- `TechnicalModel` + `TechnicalModelInput` / `TechnicalModelOutput`
- `PortfolioPolicy` + `PortfolioPolicyInput` / `PortfolioPolicyOutput`
- `LLMProvider` + `LLMMessage` / `LLMResponse`

Contracts use typed domain DTOs (not open `dict[str, Any]` for primary inputs/outputs).
Optional `metadata` fields remain a narrow JSON-scalar mapping for extensibility.
