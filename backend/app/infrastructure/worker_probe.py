"""Probe Celery worker availability via control ping."""

from __future__ import annotations

from app.core.logging import get_logger
from app.worker.celery_app import celery_app

logger = get_logger(__name__, component="infrastructure")


def check_worker() -> bool:
    try:
        inspector = celery_app.control.inspect(timeout=2.0)
        ping = inspector.ping() if inspector is not None else None
        if not ping:
            return False
        return any(isinstance(reply, dict) and reply.get("ok") == "pong" for reply in ping.values())
    except Exception as exc:  # noqa: BLE001
        logger.warning("worker_unhealthy", extra={"error": str(exc)})
        return False
