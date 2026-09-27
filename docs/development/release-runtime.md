# Kraken release runtime (image-only)

## Development (default — keep this)

- One Compose project: `projectai`
- Cursor edits host sources
- Code services bind-mount `backend/app`, `frontend/src`, …
- Persistent named volumes for PostgreSQL / Redis / raw / models

Everyday command (from the active clean worktree with a correct `.env`):

```powershell
docker compose -p projectai up -d --no-build --force-recreate backend worker scheduler frontend
```

Do **not** create a second stack (`projectai-dev`, duplicate Postgres, etc.).

## Environment / secrets

- `.env` is gitignored and must match the live DB credentials.
- Safe practice: copy from the existing live host `.env` into the clean worktree (read-only source; never commit).
- Changing the source worktree must not invent new DB passwords.

## Release mode (occasional)

Override file: `docker-compose.release.yml`

Removes source bind mounts for `backend` / `worker` / `scheduler` / `frontend`.
Keeps the same named volumes.
Frontend uses `frontend/Dockerfile.release` (static nginx on port 5173).

Prove once near release validation — do **not** keep release and bind-mounted stacks running together.

```powershell
$env:VITE_GIT_SHA = (git rev-parse HEAD)
$env:VITE_BUILD_TIME = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK")
$env:VITE_KRAKEN_VERSION = (Get-Content VERSION -Raw).Trim()

docker compose -p projectai -f docker-compose.yml -f docker-compose.release.yml build backend frontend worker scheduler
docker compose -p projectai -f docker-compose.yml -f docker-compose.release.yml up -d --no-build --force-recreate backend worker scheduler frontend
# bounded health poll, then smoke
```

Return to bind-mounted development afterwards by recreating code services with the base compose file only.
