#!/bin/sh
set -e

run_migrations() {
  echo "[entrypoint] Running core migrations..."
  alembic -c alembic_core.ini upgrade head
  echo "[entrypoint] Running memory migrations..."
  alembic -c alembic_memory.ini upgrade head
}

case "$1" in
  api)
    run_migrations
    exec uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT:-8000}" --reload
    ;;
  worker)
    exec celery -A app.worker.celery_app.celery_app worker --loglevel="${LOG_LEVEL:-INFO}"
    ;;
  scheduler)
    exec celery -A app.worker.celery_app.celery_app beat --loglevel="${LOG_LEVEL:-INFO}"
    ;;
  migrate)
    run_migrations
    ;;
  *)
    exec "$@"
    ;;
esac
