# Docker Development

## Start

```bash
copy .env.example .env
docker compose up -d --build
```

Windows (PowerShell): `Copy-Item .env.example .env`

## Hot reload

- Backend mounts `./backend/app` and runs Uvicorn `--reload`
- Frontend mounts `./frontend/src` and uses Vite HMR (`usePolling` for Windows/WSL bind mounts)

Edit files in `E:\!AI\ProjectAI` with Cursor; containers pick up changes without rebuild for most code edits.

## Useful commands

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f worker
docker compose exec backend alembic -c alembic_core.ini upgrade head
docker compose exec backend alembic -c alembic_memory.ini upgrade head
docker compose down
```

Volumes persist across `docker compose down`. Use `docker compose down -v` only when intentionally wiping data.
