"""Live (non-durable) shadow portfolio valuation from intraday LAST quotes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.ports.intraday_market import IntradayQuote, QuoteFreshness


@dataclass(slots=True, frozen=True)
class LivePositionMark:
    instrument_id: int
    ticker: str
    quantity: float
    entry_price: float | None
    mark_price: float | None
    mark_source: str
    market_value: float
    invested_cost: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    freshness: str
    quote_time: datetime | None = None


@dataclass(slots=True, frozen=True)
class LivePortfolioSnapshot:
    portfolio_id: int
    cash: float
    invested_cost: float
    market_value: float
    nav: float
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    position_marks: tuple[LivePositionMark, ...] = ()
    as_of: datetime | None = None
    quote_coverage: float = 0.0
    warnings: tuple[str, ...] = ()


def _mark_from_quote(quote: IntradayQuote | None) -> tuple[float | None, str, str, datetime | None]:
    if quote is None:
        return None, "MISSING", QuoteFreshness.UNAVAILABLE.value, None
    quote_time = quote.observed_at
    if quote.last_price is not None and float(quote.last_price) > 0:
        return float(quote.last_price), "LAST", str(quote.freshness), quote_time
    if quote.previous_close is not None and float(quote.previous_close) > 0:
        return (
            float(quote.previous_close),
            "PREVIOUS_CLOSE",
            QuoteFreshness.STALE.value,
            quote_time,
        )
    return None, "MISSING", str(quote.freshness), quote_time


def build_live_portfolio_snapshot(
    *,
    portfolio_id: int,
    cash: float,
    positions: dict[str, Any] | None,
    quotes_by_instrument: dict[int, IntradayQuote],
    entry_by_instrument: dict[int, float] | None = None,
    cost_basis_nav: float | None = None,
    as_of: datetime | None = None,
) -> LivePortfolioSnapshot:
    """Mark positions with LAST (fallback previous close → STALE). No DB writes.

    ``entry_by_instrument`` is average entry (fill) price per instrument when known.
    Portfolio unrealized P&L prefers sum of position P&L; ``cost_basis_nav`` is
    legacy fallback (NAV vs initial capital).
    """
    entries = entry_by_instrument or {}
    marks: list[LivePositionMark] = []
    warnings: list[str] = []
    market_value = 0.0
    invested_cost_total = 0.0
    covered = 0
    total = 0
    pos = positions or {}
    for key, row in pos.items():
        if not isinstance(row, dict):
            continue
        qty = float(row.get("quantity") or 0)
        if abs(qty) < 1e-12:
            continue
        total += 1
        iid = int(row.get("instrument_id") or key)
        ticker = str(row.get("ticker") or "")
        price, source, freshness, quote_time = _mark_from_quote(quotes_by_instrument.get(iid))
        entry = entries.get(iid)
        invested = (float(entry) * qty) if entry is not None else None
        if invested is not None:
            invested_cost_total += invested
        if price is None:
            warnings.append(f"no_mark:{ticker or iid}")
            marks.append(
                LivePositionMark(
                    instrument_id=iid,
                    ticker=ticker,
                    quantity=qty,
                    entry_price=entry,
                    mark_price=None,
                    mark_source=source,
                    market_value=0.0,
                    invested_cost=invested,
                    unrealized_pnl=None,
                    unrealized_pnl_pct=None,
                    freshness=freshness,
                    quote_time=quote_time,
                )
            )
            continue
        covered += 1
        mv = qty * price
        market_value += mv
        upnl = (mv - invested) if invested is not None else None
        upnl_pct = (upnl / invested) if invested is not None and abs(invested) > 1e-12 else None
        marks.append(
            LivePositionMark(
                instrument_id=iid,
                ticker=ticker,
                quantity=qty,
                entry_price=entry,
                mark_price=price,
                mark_source=source,
                market_value=mv,
                invested_cost=invested,
                unrealized_pnl=upnl,
                unrealized_pnl_pct=upnl_pct,
                freshness=freshness,
                quote_time=quote_time,
            )
        )
    nav = float(cash) + market_value
    unrealized: float | None
    if any(m.unrealized_pnl is not None for m in marks):
        unrealized = sum(m.unrealized_pnl or 0.0 for m in marks)
    elif cost_basis_nav is not None:
        unrealized = nav - float(cost_basis_nav)
    else:
        unrealized = None
    unrealized_pct = None
    if unrealized is not None and invested_cost_total > 1e-12:
        unrealized_pct = unrealized / invested_cost_total
    coverage = (covered / total) if total else 1.0
    return LivePortfolioSnapshot(
        portfolio_id=portfolio_id,
        cash=float(cash),
        invested_cost=invested_cost_total,
        market_value=market_value,
        nav=nav,
        unrealized_pnl=unrealized,
        unrealized_pnl_pct=unrealized_pct,
        position_marks=tuple(marks),
        as_of=as_of,
        quote_coverage=coverage,
        warnings=tuple(warnings),
    )
