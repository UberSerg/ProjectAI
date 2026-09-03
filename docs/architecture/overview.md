# ProjectAI Architecture Overview

ProjectAI is a **Docker-first modular monolith** for local development and later cloud/VPS
deployment without rewriting the application.

Long-term product direction: a self-learning investment system that must prove itself in
historical and virtual environments before real execution. The mature conceptual state is
called **Kraken** (not a code module). See [future-intelligence-roadmap.md](./future-intelligence-roadmap.md).

## Runtime topology

```text
Browser -> Frontend (React/Vite Control Center)
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
- `modules/*` — analytical / learning domains
- `worker` — async jobs and schedules

## Current analytical foundation

```text
Market Data V1
  → Analytics Feature Layer V1
  → Relations Engine V1
  → Technical Agent V1
  → Dataset / PIT Join V0 (accepted; `pit_daily_core` v1 frozen)
```

Later direction (not implemented): Prediction models → Meta Model → Trading Policy →
Risk → Order Intent → replaceable Execution Adapter (Simulator / Paper / Broker) →
outcomes → Learning → Decision Memory.

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

## Non-goals (unless an explicit stage requests them)

- Real broker trading / autonomous live execution
- Collapsing prediction + policy + risk + execution into one agent
- Premature Meta Model / Simulator / RL / Fundamentals / Market Regime / Deep History H1+
  implementation
- Overwriting RAW `market.candles` with adjusted or total-return prices (ADR 0005)
- Microservices, new databases, or generic ML platforms “just in case”
- Using LLM as calculator or source of truth for numbers / dates
