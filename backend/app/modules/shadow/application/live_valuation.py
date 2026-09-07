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
    mark_price: float | None
    mark_source: str
    market_value: float
    freshness: str


@dataclass(slots=True, frozen=True)
class LivePortfolioSnapshot:
    portfolio_id: int
    cash: float
    market_value: float
    nav: float
    unrealized_pnl: float | None
    position_marks: tuple[LivePositionMark, ...] = ()
    as_of: datetime | None = None
    quote_coverage: float = 0.0
    warnings: tuple[str, ...] = ()


def _mark_from_quote(quote: IntradayQuote | None) -> tuple[float | None, str, str]:
    if quote is None:
        return None, "MISSING", QuoteFreshness.UNAVAILABLE.value
    if quote.last_price is not None and float(quote.last_price) > 0:
        return float(quote.last_price), "LAST", str(quote.freshness)
    if quote.previous_close is not None and float(quote.previous_close) > 0:
        return float(quote.previous_close), "PREVIOUS_CLOSE", QuoteFreshness.STALE.value
    return None, "MISSING", str(quote.freshness)


def build_live_portfolio_snapshot(
    *,
    portfolio_id: int,
    cash: float,
    positions: dict[str, Any] | None,
    quotes_by_instrument: dict[int, IntradayQuote],
    cost_basis_nav: float | None = None,
    as_of: datetime | None = None,
) -> LivePortfolioSnapshot:
    """Mark positions with LAST (fallback previous close → STALE). No DB writes."""
    marks: list[LivePositionMark] = []
    warnings: list[str] = []
    market_value = 0.0
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
        price, source, freshness = _mark_from_quote(quotes_by_instrument.get(iid))
        if price is None:
            warnings.append(f"no_mark:{ticker or iid}")
            marks.append(
                LivePositionMark(
                    instrument_id=iid,
                    ticker=ticker,
                    quantity=qty,
                    mark_price=None,
                    mark_source=source,
                    market_value=0.0,
                    freshness=freshness,
                )
            )
            continue
        covered += 1
        mv = qty * price
        market_value += mv
        marks.append(
            LivePositionMark(
                instrument_id=iid,
                ticker=ticker,
                quantity=qty,
                mark_price=price,
                mark_source=source,
                market_value=mv,
                freshness=freshness,
            )
        )
    nav = float(cash) + market_value
    unrealized = None
    if cost_basis_nav is not None:
        unrealized = nav - float(cost_basis_nav)
    coverage = (covered / total) if total else 1.0
    return LivePortfolioSnapshot(
        portfolio_id=portfolio_id,
        cash=float(cash),
        market_value=market_value,
        nav=nav,
        unrealized_pnl=unrealized,
        position_marks=tuple(marks),
        as_of=as_of,
        quote_coverage=coverage,
        warnings=tuple(warnings),
    )
