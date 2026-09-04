# ProjectAI

Docker-first modular monolith for local development in Cursor and later cloud/VPS deployment.

Long-term direction: a self-learning investment system that must prove itself on historical
data and in virtual environments before real execution. The mature conceptual state is called
**Kraken** (not a code module). See `docs/architecture/future-intelligence-roadmap.md`.

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

**Implemented foundation:**

```text
Market Data V1
  → Analytics Feature Layer V1
  → Relations Engine V1
  → Technical Agent V1
  → Dataset / PIT Join V0 (`pit_daily_core` v1 frozen)
  → Dataset / PIT V2 deep history (`pit_daily_core` v2; mechanical Y; not active)
  → Prediction ML Candidate V0 (offline CatBoost walk-forward; MIXED; not champion)
  → Historical Simulator V0 (OOS predictions → RANK_LONG_ONLY_V0 → next-open ledger; no real execution)
  → Simulator Dashboard V0 (research UI for persisted runs; not profitability proof)
```

**Target direction (mostly not implemented):**

```text
PIT Dataset → Prediction Models → Meta Model → Trading Policy → Risk
  → Order Intent → Execution Adapter (Simulator | Paper | Broker)
  → Outcomes → Learning / Retraining → Decision Memory
```

Historical Simulator V0 implements the research path from OOS predictions through a
diagnostic Trading Policy / Risk guardrails / Historical Execution Adapter. Dividends,
historical universe, broker execution, and champion promotion are still deferred.

Simulator Dashboard V0 visualizes persisted simulation runs (NAV vs IMOEX, drawdown,
positions, fills, cost sensitivity). It does **not** claim Kraken is profitable or ready
for real trading.

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

## AI-assisted development

ProjectAI uses repository-level Cursor rules from `.cursor/rules/`.

The complete development and review workflow is documented in:

`docs/development/AI_WORKFLOW.md`

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
