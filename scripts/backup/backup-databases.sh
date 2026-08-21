#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${1:-${ROOT_DIR}/backups}"
mkdir -p "${OUT_DIR}"
STAMP="$(date +%Y%m%d_%H%M%S)"

docker exec projectai-postgres-core pg_dump -U projectai -d projectai_core -Fc -f /tmp/core.dump
docker cp projectai-postgres-core:/tmp/core.dump "${OUT_DIR}/core_${STAMP}.dump"

docker exec projectai-postgres-memory pg_dump -U projectai -d projectai_memory -Fc -f /tmp/memory.dump
docker cp projectai-postgres-memory:/tmp/memory.dump "${OUT_DIR}/memory_${STAMP}.dump"

echo "Backups written to ${OUT_DIR}"
ls -lah "${OUT_DIR}" | tail -n 10
