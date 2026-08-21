"""Celery tasks — technical foundation only."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.worker.celery_app import celery_app

logger = get_logger(__name__, component="worker")


@celery_app.task(name="projectai.ping")
def ping() -> dict[str, str]:
    """Safe technical health task for worker verification."""
    logger.info("ping_task_executed")
    return {"status": "pong", "timestamp": datetime.now(UTC).isoformat()}
