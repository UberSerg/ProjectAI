"""Health check orchestration: liveness, readiness, system diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.infrastructure.db.session import check_core_database, check_memory_database
from app.infrastructure.redis_client import check_redis
from app.infrastructure.worker_probe import check_worker

ServiceStatus = Literal["ok", "error"]


@dataclass(slots=True)
class LivenessResult:
    status: ServiceStatus


@dataclass(slots=True)
class HealthResult:
    status: ServiceStatus
    services: dict[str, ServiceStatus]


def get_liveness() -> LivenessResult:
    """Process is alive and can answer HTTP — no dependency checks."""
    return LivenessResult(status="ok")


def get_readiness() -> HealthResult:
    """Ready to serve ordinary API traffic (required infra only)."""
    services: dict[str, ServiceStatus] = {
        "core_database": "ok" if check_core_database() else "error",
        "memory_database": "ok" if check_memory_database() else "error",
        "redis": "ok" if check_redis() else "error",
    }
    overall: ServiceStatus = "ok" if all(v == "ok" for v in services.values()) else "error"
    return HealthResult(status=overall, services=services)


def get_system_health() -> HealthResult:
    """Full ProjectAI diagnostics for dashboard (includes worker)."""
    services: dict[str, ServiceStatus] = {
        "backend": "ok",
        "core_database": "ok" if check_core_database() else "error",
        "memory_database": "ok" if check_memory_database() else "error",
        "redis": "ok" if check_redis() else "error",
        "worker": "ok" if check_worker() else "error",
    }
    overall: ServiceStatus = "ok" if all(v == "ok" for v in services.values()) else "error"
    return HealthResult(status=overall, services=services)
