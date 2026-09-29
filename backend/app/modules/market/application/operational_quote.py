"""Operational current quotes for portfolio marks (ephemeral; never market.candles).

Cold-start path after empty IntradayQuoteCache: fetch LAST/PREVPRICE via
MoexIntradayProvider board securities.json. Does not invent historical candles
or set InstrumentSource.valid_from.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domain.ports.intraday_market import IntradayMarketPort, IntradayQuote
from app.infrastructure.market.models import Instrument, InstrumentSource
from app.modules.market.application.intraday_cache import IntradayQuoteCache

logger = get_logger(__name__, component="market")

Quality = Literal["LIVE", "PARTIAL", "STALE", "UNSUPPORTED"]

PREFERRED_BOARDS = ("TQBR", "TQTF", "SMAL")


def _d(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def resolve_board_secid(session: Session, instrument: Instrument) -> tuple[str, str]:
    """Board/SECID for operational MOEX quote (current mapping only)."""
    sources = list(
        session.scalars(
            select(InstrumentSource).where(
                InstrumentSource.instrument_id == int(instrument.id),
                InstrumentSource.source.in_(("MOEX", "MOEX_ISS")),
                InstrumentSource.valid_to.is_(None),
            )
        )
    )
    by_board = {str(s.board or "").upper(): s for s in sources if s.board}
    picked: InstrumentSource | None = None
    for board in PREFERRED_BOARDS:
        if board in by_board:
            picked = by_board[board]
            break
    if picked is None and sources:
        picked = sources[0]
    if picked is not None:
        board = str(picked.board or instrument.primary_board or "TQBR").upper()
        secid = str(picked.external_id or instrument.symbol).upper()
        return board, secid
    board = str(instrument.primary_board or "TQBR").upper()
    return board, str(instrument.symbol).upper()


def mark_from_intraday_quote(
    quote: IntradayQuote | None,
) -> tuple[Decimal | None, str, Quality]:
    """LAST preferred; PREVPRICE/previous_close is STALE operational mark — never invent."""
    if quote is None:
        return None, "NONE", "UNSUPPORTED"
    if quote.last_price is not None and float(quote.last_price) > 0:
        return _d(quote.last_price), "INTRADAY_LAST", "LIVE"
    if quote.previous_close is not None and float(quote.previous_close) > 0:
        return _d(quote.previous_close), "PREVIOUS_CLOSE", "STALE"
    return None, "NONE", "UNSUPPORTED"


def ensure_operational_quotes(
    session: Session,
    instruments: list[Instrument],
    *,
    cache: IntradayQuoteCache | None = None,
    provider: IntradayMarketPort | None = None,
) -> dict[tuple[str, str], IntradayQuote]:
    """Batch-fetch missing board quotes and cache them. Returns board/secid → quote."""
    if not instruments:
        return {}
    quote_cache = cache or IntradayQuoteCache()
    needed: dict[str, set[str]] = {}
    resolved: dict[int, tuple[str, str]] = {}
    for inst in instruments:
        board, secid = resolve_board_secid(session, inst)
        resolved[int(inst.id)] = (board, secid)
        if quote_cache.get(board, secid) is None:
            needed.setdefault(board, set()).add(secid)

    out: dict[tuple[str, str], IntradayQuote] = {}
    for board, secid in resolved.values():
        cached = quote_cache.get(board, secid)
        if cached is not None:
            out[(board, secid)] = cached

    if not needed:
        return out

    from app.core.config import get_settings
    from app.infrastructure.market.moex_intraday import MoexIntradayProvider

    settings = get_settings()
    prov = provider or MoexIntradayProvider(
        timeout_seconds=float(settings.intraday_http_timeout_seconds)
    )
    observed_at = datetime.now(UTC)
    try:
        fetched = prov.fetch_quotes(
            {b: sorted(s) for b, s in needed.items()},
            observed_at=observed_at,
        )
    except Exception as exc:  # noqa: BLE001 — valuation must degrade, not crash
        logger.warning("operational_quote_fetch_failed", extra={"error": str(exc)})
        return out

    for quote in fetched:
        key = (str(quote.board).upper(), str(quote.secid).upper())
        quote_cache.set(quote)
        out[key] = quote
    return out


def ensure_operational_quote(
    session: Session,
    instrument: Instrument,
    *,
    cache: IntradayQuoteCache | None = None,
    provider: IntradayMarketPort | None = None,
) -> IntradayQuote | None:
    """Cold-start one instrument quote (cache hit preferred)."""
    board, secid = resolve_board_secid(session, instrument)
    quote_cache = cache or IntradayQuoteCache()
    hit = quote_cache.get(board, secid)
    if hit is not None:
        return hit
    got = ensure_operational_quotes(
        session, [instrument], cache=quote_cache, provider=provider
    )
    return got.get((board, secid))


def price_unavailable_detail(*, has_moex_source: bool, tried_fetch: bool) -> dict[str, Any]:
    if not has_moex_source:
        return {"reason": "price_unavailable", "code": "NO_MOEX_SOURCE"}
    if tried_fetch:
        return {"reason": "price_unavailable", "code": "MOEX_QUOTE_UNAVAILABLE"}
    return {"reason": "price_unavailable", "code": "NO_INTRADAY_OR_EOD"}
