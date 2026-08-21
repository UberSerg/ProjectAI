"""Health check orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.infrastructure.db.session import check_core_database, check_memory_database
from app.infrastructure.redis_client import check_redis
from app.infrastructure.worker_probe import check_worker

ServiceStatus = Literal["ok", "error"]


@dataclass(slots=True)
class HealthResult:
    status: ServiceStatus
    services: dict[str, ServiceStatus]


def get_system_health() -> HealthResult:
    services: dict[str, ServiceStatus] = {
        "core_database": "ok" if check_core_database() else "error",
        "memory_database": "ok" if check_memory_database() else "error",
        "redis": "ok" if check_redis() else "error",
        "worker": "ok" if check_worker() else "error",
    }
    overall: ServiceStatus = "ok" if all(v == "ok" for v in services.values()) else "error"
    return HealthResult(status=overall, services=services)
