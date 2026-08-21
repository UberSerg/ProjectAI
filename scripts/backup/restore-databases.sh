#!/usr/bin/env bash
set -euo pipefail
CORE_DUMP="${1:?Usage: restore-databases.sh <core.dump> <memory.dump>}"
MEMORY_DUMP="${2:?Usage: restore-databases.sh <core.dump> <memory.dump>}"

docker cp "${CORE_DUMP}" projectai-postgres-core:/tmp/restore_core.dump
docker exec projectai-postgres-core pg_restore -U projectai -d projectai_core --clean --if-exists /tmp/restore_core.dump

docker cp "${MEMORY_DUMP}" projectai-postgres-memory:/tmp/restore_memory.dump
docker exec projectai-postgres-memory pg_restore -U projectai -d projectai_memory --clean --if-exists /tmp/restore_memory.dump

echo "Restore completed."
