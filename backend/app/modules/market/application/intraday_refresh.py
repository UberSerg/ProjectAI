"""Orchestrate intraday quote refresh + shadow session-open execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import redis
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.ports.intraday_market import IntradayMarketPort, IntradayQuote
from app.infrastructure.market.moex_intraday import MoexIntradayProvider
from app.modules.market.application.intraday_cache import IntradayQuoteCache
from app.modules.shadow.application.intraday_universe import (
    group_secids_by_board,
    resolve_intraday_universe,
)
from app.modules.shadow.application.open_execution_service import (
    fill_pending_orders_with_session_open,
)

logger = get_logger(__name__, component="intraday")

LOCK_KEY = "projectai:lock:intraday_refresh"
LOCK_TTL_SECONDS = 240


@dataclass
class IntradayRefreshResult:
    status: str
    enabled: bool
    quotes_fetched: int = 0
    quotes_cached: int = 0
    universe_size: int = 0
    filled: int = 0
    skipped: int = 0
    reasons: list[dict[str, Any]] = field(default_factory=list)
    last_refresh_at: str | None = None
    error: str | None = None


def _lock_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=False)


def try_acquire_intraday_lock(token: str, *, ttl: int = LOCK_TTL_SECONDS) -> bool:
    try:
        return bool(_lock_client().set(LOCK_KEY, token, nx=True, ex=ttl))
    except Exception as exc:  # noqa: BLE001
        logger.warning("intraday_lock_unavailable", extra={"error": str(exc)})
        return False


def release_intraday_lock(token: str) -> None:
    try:
        client = _lock_client()
        current = client.get(LOCK_KEY)
        if current is not None and current.decode() == token:
            client.delete(LOCK_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.warning("intraday_lock_release_failed", extra={"error": str(exc)})


def attach_instrument_ids(
    quotes: list[IntradayQuote],
    instrument_by_secid: dict[tuple[str, str], int],
) -> list[IntradayQuote]:
    out: list[IntradayQuote] = []
    for q in quotes:
        iid = instrument_by_secid.get((q.board.upper(), q.secid.upper()))
        if iid is None or q.instrument_id == iid:
            out.append(q)
            continue
        out.append(
            IntradayQuote(
                secid=q.secid,
                board=q.board,
                trading_date=q.trading_date,
                observed_at=q.observed_at,
                source_timestamp=q.source_timestamp,
                market_status=q.market_status,
                open_price=q.open_price,
                last_price=q.last_price,
                bid=q.bid,
                ask=q.ask,
                previous_close=q.previous_close,
                volume=q.volume,
                source=q.source,
                freshness=q.freshness,
                quality=q.quality,
                instrument_id=iid,
            )
        )
    return out


def run_intraday_refresh(
    session: Session,
    *,
    provider: IntradayMarketPort | None = None,
    cache: IntradayQuoteCache | None = None,
    acquire_lock: bool = True,
) -> IntradayRefreshResult:
    """Resolve universe → fetch → cache → open execution. No research cycle."""
    settings = get_settings()
    if not settings.intraday_market_enabled:
        return IntradayRefreshResult(status="DISABLED", enabled=False)

    token = uuid4().hex
    if acquire_lock and not try_acquire_intraday_lock(token):
        return IntradayRefreshResult(status="SKIPPED_LOCK", enabled=True)

    try:
        members = resolve_intraday_universe(session)
        instrument_by_secid = {(m.board, m.secid): m.instrument_id for m in members}
        secids_by_board = group_secids_by_board(members)
        observed_at = datetime.now(UTC)
        prov = provider or MoexIntradayProvider(
            timeout_seconds=float(settings.intraday_http_timeout_seconds)
        )
        quotes = prov.fetch_quotes(secids_by_board, observed_at=observed_at)
        quotes = attach_instrument_ids(quotes, instrument_by_secid)
        quote_cache = cache or IntradayQuoteCache()
        cached = quote_cache.set_many(quotes)
        exec_result = fill_pending_orders_with_session_open(
            session,
            quotes=quotes,
            instrument_by_secid=instrument_by_secid,
            now=observed_at,
        )
        metrics = {
            "universe_size": len(members),
            "quotes_fetched": len(quotes),
            "quotes_cached": cached,
            "filled": exec_result.filled,
            "skipped": exec_result.skipped,
        }
        quote_cache.set_last_refresh(observed_at, metrics=metrics)
        logger.info("intraday_refresh_complete", extra=metrics)
        return IntradayRefreshResult(
            status="SUCCESS",
            enabled=True,
            quotes_fetched=len(quotes),
            quotes_cached=cached,
            universe_size=len(members),
            filled=exec_result.filled,
            skipped=exec_result.skipped,
            reasons=[
                {
                    "order_id": r.order_id,
                    "portfolio_id": r.portfolio_id,
                    "ticker": r.ticker,
                    "reason": r.reason,
                    "session_date": r.session_date,
                    "delayed_observation": r.delayed_observation,
                }
                for r in (exec_result.reasons or [])
            ],
            last_refresh_at=observed_at.isoformat(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("intraday_refresh_failed")
        return IntradayRefreshResult(
            status="ERROR",
            enabled=True,
            error=str(exc),
        )
    finally:
        if acquire_lock:
            release_intraday_lock(token)
