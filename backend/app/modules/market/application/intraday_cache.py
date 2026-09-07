"""Ephemeral Redis cache for intraday quotes (never durable market history)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.ports.intraday_market import (
    IntradayQuote,
    MarketSessionStatus,
    QuoteFreshness,
)
from app.infrastructure.redis_client import get_redis

logger = get_logger(__name__, component="market")

KEY_PREFIX = "projectai:intraday"
META_LAST_REFRESH_KEY = "projectai:intraday:last_refresh"


def quote_key(board: str, secid: str) -> str:
    return f"{KEY_PREFIX}:{str(board).upper()}:{str(secid).upper()}"


def _dt_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _date_to_iso(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def quote_to_dict(quote: IntradayQuote) -> dict[str, Any]:
    raw = asdict(quote)
    raw["trading_date"] = _date_to_iso(quote.trading_date)
    raw["observed_at"] = _dt_to_iso(quote.observed_at)
    raw["source_timestamp"] = _dt_to_iso(quote.source_timestamp)
    raw["market_status"] = str(quote.market_status)
    raw["freshness"] = str(quote.freshness)
    return raw


def quote_from_dict(payload: dict[str, Any]) -> IntradayQuote:
    trading_date = payload.get("trading_date")
    observed_at = payload["observed_at"]
    source_timestamp = payload.get("source_timestamp")
    return IntradayQuote(
        secid=str(payload["secid"]),
        board=str(payload["board"]),
        trading_date=date.fromisoformat(trading_date) if trading_date else None,
        observed_at=datetime.fromisoformat(str(observed_at)),
        source_timestamp=(
            datetime.fromisoformat(str(source_timestamp)) if source_timestamp else None
        ),
        market_status=MarketSessionStatus(str(payload["market_status"])),
        open_price=payload.get("open_price"),
        last_price=payload.get("last_price"),
        bid=payload.get("bid"),
        ask=payload.get("ask"),
        previous_close=payload.get("previous_close"),
        volume=payload.get("volume"),
        source=str(payload.get("source") or "MOEX_ISS"),
        freshness=QuoteFreshness(str(payload["freshness"])),
        quality=str(payload.get("quality") or ""),
        instrument_id=payload.get("instrument_id"),
    )


class IntradayQuoteCache:
    """get/set/get_many — returns None when Redis is unavailable (never fakes)."""

    def __init__(self, *, ttl_seconds: int | None = None, client: Any | None = None) -> None:
        settings = get_settings()
        self.ttl_seconds = (
            int(settings.intraday_cache_ttl_seconds) if ttl_seconds is None else int(ttl_seconds)
        )
        self._client = client

    def _redis(self) -> Any | None:
        if self._client is not None:
            return self._client
        try:
            return get_redis()
        except Exception as exc:  # noqa: BLE001
            logger.warning("intraday_cache_redis_unavailable", extra={"error": str(exc)})
            return None

    def set(self, quote: IntradayQuote) -> bool:
        client = self._redis()
        if client is None:
            return False
        try:
            client.set(
                quote_key(quote.board, quote.secid),
                json.dumps(quote_to_dict(quote), separators=(",", ":")),
                ex=self.ttl_seconds,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("intraday_cache_set_failed", extra={"error": str(exc)})
            return False

    def set_many(self, quotes: list[IntradayQuote]) -> int:
        n = 0
        for quote in quotes:
            if self.set(quote):
                n += 1
        return n

    def get(self, board: str, secid: str) -> IntradayQuote | None:
        client = self._redis()
        if client is None:
            return None
        try:
            raw = client.get(quote_key(board, secid))
        except Exception as exc:  # noqa: BLE001
            logger.warning("intraday_cache_get_failed", extra={"error": str(exc)})
            return None
        if raw in (None, ""):
            return None
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            return quote_from_dict(payload)
        except (TypeError, ValueError, KeyError) as exc:
            logger.warning("intraday_cache_decode_failed", extra={"error": str(exc)})
            return None

    def get_many(self, board_secids: list[tuple[str, str]]) -> dict[tuple[str, str], IntradayQuote]:
        out: dict[tuple[str, str], IntradayQuote] = {}
        for board, secid in board_secids:
            quote = self.get(board, secid)
            if quote is not None:
                out[(str(board).upper(), str(secid).upper())] = quote
        return out

    def set_last_refresh(self, when: datetime, *, metrics: dict[str, Any] | None = None) -> bool:
        client = self._redis()
        if client is None:
            return False
        payload = {
            "at": when.isoformat(),
            "metrics": metrics or {},
        }
        try:
            client.set(
                META_LAST_REFRESH_KEY,
                json.dumps(payload, separators=(",", ":")),
                ex=max(self.ttl_seconds * 2, 3600),
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("intraday_cache_meta_failed", extra={"error": str(exc)})
            return False

    def get_last_refresh(self) -> dict[str, Any] | None:
        client = self._redis()
        if client is None:
            return None
        try:
            raw = client.get(META_LAST_REFRESH_KEY)
        except Exception as exc:  # noqa: BLE001
            logger.warning("intraday_cache_meta_get_failed", extra={"error": str(exc)})
            return None
        if raw in (None, ""):
            return None
        try:
            payload = json.loads(raw)
            return payload if isinstance(payload, dict) else None
        except (TypeError, ValueError):
            return None
