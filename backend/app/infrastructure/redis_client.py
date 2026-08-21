"""Redis client for Celery coordination and short-lived cache."""

from __future__ import annotations

import redis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__, component="infrastructure")

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


def check_redis() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_unhealthy", extra={"error": str(exc)})
        return False
