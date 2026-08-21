# ProjectAI

Docker-first modular monolith foundation for local development in Cursor and later cloud/VPS deployment.

> Historical conceptual documents (`docs/legacy/`, root `*.markdown`, `docs/specs/`) are preserved for project history.
> They are **not** the current architectural specification. This `README.md` and `docs/architecture/` take priority.

## Requirements

- Docker Desktop with Linux containers (WSL2 backend recommended on Windows)
- Git
- Free local ports: `5173`, `8000`, `5432`, `5433`, `6379`

No local PostgreSQL, Redis, Node, or Python install is required for running the stack.

## Quick start

```bash
git clone https://github.com/UberSerg/ProjectAI
cd ProjectAI
copy .env.example .env
docker compose up -d --build
```

PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

## URLs

| Service | URL |
|---------|-----|
| Frontend dashboard | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| OpenAPI docs | http://localhost:8000/docs |
| Liveness | http://localhost:8000/api/v1/system/health/live |
| Readiness | http://localhost:8000/api/v1/system/health/ready |
| System health (dashboard) | http://localhost:8000/api/v1/system/health |
| Info | http://localhost:8000/api/v1/system/info |

### Health endpoints

| Endpoint | Purpose | Checks |
|----------|---------|--------|
| `/api/v1/system/health/live` | Docker/process liveness | FastAPI process only |
| `/api/v1/system/health/ready` | Readiness for ordinary traffic | Core DB, Memory DB, Redis |
| `/api/v1/system/health` | ProjectAI diagnostics / dashboard | Backend + DBs + Redis + Celery worker |

## Containers

- `frontend` — React + Vite dashboard
- `backend` — FastAPI API
- `worker` — Celery worker
- `scheduler` — Celery Beat
- `postgres-core` — operational PostgreSQL
- `postgres-memory` — Decision Memory PostgreSQL + pgvector
- `redis` — Celery broker/cache

## Architecture (short)

```text
Market Data -> Analyzers -> Meta Model -> Decision Memory -> Expert LLM
 -> Recommendation -> Portfolio Manager -> Virtual Portfolio -> Outcomes
 -> Training / Retraining
```

Business logic above is **not implemented yet**. Only platform boundaries, dual DB, workers, and dashboard health are in place.

See `docs/architecture/`.

## Market Data V1

MOEX ISS + Bank of Russia ingestion, raw volume storage, workflows and admin UI.

```text
POST /api/v1/market/backfill
POST /api/v1/market/update
GET  /api/v1/market/instruments
GET  /api/v1/workflows
```

Details: `docs/market-data/`. Scheduler remains off by default (`MARKET_UPDATE_ENABLED=false`).

## Common commands

```bash
docker compose ps
docker compose logs -f backend worker frontend
docker compose down
```

## Migrations

Applied automatically on backend start. Manual:

```bash
docker compose exec backend alembic -c alembic_core.ini upgrade head
docker compose exec backend alembic -c alembic_memory.ini upgrade head
```

## Tests

Backend:

```bash
docker compose exec backend pytest -q
```

Frontend (in container or CI):

```bash
docker compose run --rm frontend npm test
docker compose run --rm frontend npm run build
```

Smoke (after stack is up):

```powershell
./scripts/smoke-docker.ps1
```

## Backup / restore

Backups are written to `backups/` (gitignored).

```powershell
./scripts/backup/backup-databases.ps1
./scripts/backup/restore-databases.ps1 -CoreDump .\backups\core_XXX.dump -MemoryDump .\backups\memory_XXX.dump
```

Linux/VPS:

```bash
./scripts/backup/backup-databases.sh
./scripts/backup/restore-databases.sh ./backups/core_XXX.dump ./backups/memory_XXX.dump
```

## Configuration

Copy `.env.example` → `.env`. Never commit real secrets. Polza keys stay empty until LLM integration stage.

## Ports

| Port | Service |
|------|---------|
| 5173 | Frontend |
| 8000 | Backend |
| 5432 | Core PostgreSQL |
| 5433 | Memory PostgreSQL |
| 6379 | Redis |
