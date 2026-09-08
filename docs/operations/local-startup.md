# Local Kraken startup (Docker Compose)

## Normal daily use

1. Start **Docker Desktop** and wait until it is running.
2. Double-click **`start-kraken.cmd`** (or run `.\start-kraken.ps1`).
3. Open **http://localhost:5173**.

No Cursor. No manual `docker start` of individual containers.

## Stop (safe)

Double-click **`stop-kraken.cmd`** or run `.\stop-kraken.ps1`.

This runs `docker compose stop` and **preserves volumes** (Postgres / Redis data).

It does **not** run `docker compose down -v`, prune, or recreate databases.

## Status

Double-click **`status-kraken.cmd`** or:

```powershell
.\status-kraken.ps1
.\status-kraken.ps1 -Json
```

## Restart

```powershell
.\restart-kraken.ps1
.\restart-kraken.ps1 -Build   # after Dockerfile / dependency changes
```

## After code changes

| Change | Action |
|--------|--------|
| Python/React source (bind-mounted) | Usually hot-reload; otherwise `.\restart-kraken.ps1` |
| Dockerfile / pyproject / package.json | `.\start-kraken.ps1 -Build` or `.\restart-kraken.ps1 -Build` |
| `.env` | `.\restart-kraken.ps1` |

## Why one launcher?

Compose already uses:

- `restart: unless-stopped`
- healthchecks (`pg_isready`, `redis-cli ping`, backend `/health/ready`, …)
- `depends_on: condition: service_healthy`

**But** containers that were **explicitly stopped** (`compose stop`, Docker Desktop stop, partial shutdown) stay stopped. `unless-stopped` does not bring them back until you run `docker compose up` again.

`start-kraken` always converges the full project (`name: projectai`) to the desired state with `docker compose up -d --wait`.

## Required vs important

| Service | Role |
|---------|------|
| postgres-core | **Required** |
| postgres-memory | **Required** (readiness / Decision Memory) |
| redis | **Required** |
| backend | **Required** |
| frontend | **Required** |
| worker | **Operationally required** for LIVE research / enrichment |
| scheduler | **Operationally required** for beat / autonomy |

External MOEX / CBR providers are **not** readiness blockers.

## Troubleshooting

### Docker Desktop not running

Message:

`Docker Desktop не запущен. Запустите Docker Desktop и повторите Start Kraken.`

### `.env` missing

Copy from `.env.example`. Do not invent secrets blindly.

### A service unhealthy

`start-kraken` prints the failed service and a short log tail.

Then:

1. Ensure Docker Desktop is healthy.
2. Run `start-kraken` again.
3. Run `status-kraken`.

**Do not** delete volumes or run `docker compose down -v` as a first step.

### Port conflict

Free host ports `5173`, `8000`, `5432`, `5433`, `6379` (or change `HOST_*` in `.env`).

### Redis quotes empty after restart

Intraday Redis cache is ephemeral. Background refresh restores it. Not a startup failure.

## Destructive commands (never for daily use)

Never for normal startup:

- `docker compose down -v`
- `docker volume prune`
- `docker system prune`
- Alembic downgrade / DB recreate

## Compose project name

Compose file sets `name: projectai` so the stack is stable regardless of the shell's current directory name.
