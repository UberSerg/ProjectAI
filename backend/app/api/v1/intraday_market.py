"""Intraday market status API (ephemeral quotes; no candle writes)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.config import get_settings
from app.modules.market.application.intraday_cache import IntradayQuoteCache
from app.worker import tasks as worker_tasks

router = APIRouter()


@router.get("/intraday/status")
def intraday_market_status() -> dict[str, Any]:
    settings = get_settings()
    cache = IntradayQuoteCache()
    last = cache.get_last_refresh()
    return {
        "enabled": bool(settings.intraday_market_enabled),
        "refresh_minutes": int(settings.intraday_refresh_minutes),
        "cache_ttl_seconds": int(settings.intraday_cache_ttl_seconds),
        "http_timeout_seconds": float(settings.intraday_http_timeout_seconds),
        "persistence": "redis_ephemeral_only",
        "writes_market_candles": False,
        "policy": "SHADOW_NEXT_SESSION_OPEN_V1",
        "last_refresh": last,
        "operations": {
            "beat_registered_when_enabled": True,
            "task_name": "projectai.refresh_intraday_market",
            "lock_key": "projectai:lock:intraday_refresh",
        },
    }


@router.post("/intraday/refresh")
def enqueue_intraday_refresh() -> dict[str, Any]:
    """Manual operator trigger — same path as beat, no research cycle."""
    settings = get_settings()
    if not settings.intraday_market_enabled:
        return {
            "status": "DISABLED",
            "enabled": False,
            "detail": "INTRADAY_MARKET_ENABLED=false",
        }
    async_result = worker_tasks.refresh_intraday_market.delay()
    return {
        "status": "ENQUEUED",
        "enabled": True,
        "task_id": async_result.id,
        "task_name": "projectai.refresh_intraday_market",
    }
