# ProjectAI Architecture Overview

ProjectAI is a **modular monolith** designed for Docker-first local development and later cloud/VPS deployment without rewriting the application.

## Runtime topology

```text
Browser -> Frontend (React/Vite)
              |
           REST /api/v1
              |
           Backend (FastAPI)
              |
   +----------+-----------+-----------+
   |          |           |           |
 Core DB   Memory DB    Redis      Celery
 (ops)   (Decision      broker    Worker +
          Memory +                 Beat
          pgvector)
```

## Layer boundaries

- `api` — HTTP adapters
- `application` — use-cases
- `domain` — entities/ports (no FastAPI/SQLAlchemy/Celery)
- `infrastructure` — DB, Redis, LLM/ML adapters
- `modules/*` — future analytical domains
- `worker` — async jobs and schedules

## Health model

| Endpoint | Role |
|----------|------|
| `GET /api/v1/system/health/live` | Liveness — process can answer; used by Docker backend healthcheck |
| `GET /api/v1/system/health/ready` | Readiness — Core DB + Memory DB + Redis |
| `GET /api/v1/system/health` | System diagnostics — also probes Celery worker; used by dashboard |

Do not wire Docker `depends_on` to worker via the system health endpoint (avoids circular startup).

## Domain ports

Replaceable adapters behind typed contracts in `app/domain/ports`:

- `TechnicalModel` (`TechnicalModelInput` / `TechnicalModelOutput`)
- `PortfolioPolicy` (`PortfolioPolicyInput` / `PortfolioPolicyOutput`)
- `LLMProvider` (`LLMMessage` / `LLMResponse`)

## Non-goals (current stage)

No trading strategies, MOEX ingestion, ML training, Polza live calls, or BUY/SELL recommendations.
