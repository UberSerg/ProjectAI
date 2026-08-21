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

## Non-goals (current stage)

No trading strategies, MOEX ingestion, ML training, Polza live calls, or BUY/SELL recommendations.
