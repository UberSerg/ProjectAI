"""Live (non-durable) shadow portfolio valuation from intraday LAST quotes + EOD fallback.

Missing marks are never treated as zero market value. Partial coverage must not
produce a full-portfolio NAV or total P&L vs initial capital.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.domain.ports.intraday_market import IntradayQuote, QuoteFreshness


class ValuationStatus(StrEnum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class ValuationFreshness(StrEnum):
    """Portfolio-level mark freshness — orthogonal to FULL/PARTIAL coverage."""

    FRESH = "FRESH"
    STALE = "STALE"
    MIXED = "MIXED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(slots=True, frozen=True)
class EodMark:
    """Last known EOD close for advisory live mark (never an execution price)."""

    price: float
    as_of: datetime | None
    source: str = "EOD"


@dataclass(slots=True, frozen=True)
class LivePositionMark:
    instrument_id: int
    ticker: str
    quantity: float
    entry_price: float | None
    mark_price: float | None
    mark_source: str
    market_value: float | None
    invested_cost: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    freshness: str
    quote_time: datetime | None = None
    priced: bool = False


@dataclass(slots=True, frozen=True)
class LivePortfolioSnapshot:
    portfolio_id: int
    cash: float
    invested_cost: float
    """Sum of market values for priced positions only (not a full portfolio NAV)."""
    known_market_value: float
    """Authoritative NAV only when valuation_status == FULL; else None."""
    nav: float | None
    """Partial sum cash + known_market_value — never present as full NAV."""
    known_nav: float
    valuation_status: ValuationStatus
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    """Unrealized on priced positions only; never total-portfolio P&L when PARTIAL."""
    partial_unrealized_pnl: float | None
    position_marks: tuple[LivePositionMark, ...] = ()
    unpriced_positions: tuple[dict[str, Any], ...] = ()
    as_of: datetime | None = None
    quote_coverage: float = 0.0
    value_coverage: float = 0.0
    warnings: tuple[str, ...] = ()
    """Coverage completeness ≠ mark freshness. FULL may still be STALE."""
    valuation_freshness: ValuationFreshness = ValuationFreshness.UNAVAILABLE
    marks_as_of: datetime | None = None

    @property
    def market_value(self) -> float:
        """Backward-compatible alias: known priced market value (not inventing zeros)."""
        return self.known_market_value

    @property
    def nav_is_complete(self) -> bool:
        return self.valuation_status == ValuationStatus.FULL and self.nav is not None

    @property
    def nav_is_fresh(self) -> bool:
        return (
            self.nav_is_complete
            and self.valuation_freshness == ValuationFreshness.FRESH
        )


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
    eod_marks_by_instrument: dict[int, EodMark] | None = None,
    as_of: datetime | None = None,
) -> LivePortfolioSnapshot:
    """Mark positions with LAST → previous_close → optional EOD. No DB writes.

    Missing marks do **not** contribute 0 to market value. Full-portfolio NAV and
    total unrealized vs initial capital are only set when every open position is priced.
    """
    entries = entry_by_instrument or {}
    eod_marks = eod_marks_by_instrument or {}
    marks: list[LivePositionMark] = []
    unpriced: list[dict[str, Any]] = []
    warnings: list[str] = []
    known_market_value = 0.0
    invested_cost_total = 0.0
    invested_priced = 0.0
    partial_unrealized = 0.0
    has_partial_upnl = False
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
        if price is None:
            eod = eod_marks.get(iid)
            if eod is not None and eod.price > 0:
                price = float(eod.price)
                source = "EOD"
                freshness = QuoteFreshness.STALE.value
                quote_time = eod.as_of
                warnings.append(f"eod_fallback:{ticker or iid}")
        entry = entries.get(iid)
        invested = (float(entry) * qty) if entry is not None else None
        if invested is not None:
            invested_cost_total += invested
        if price is None:
            warnings.append(f"no_mark:{ticker or iid}")
            unpriced.append(
                {
                    "instrument_id": iid,
                    "ticker": ticker,
                    "quantity": qty,
                    "reason": "MISSING_QUOTE",
                    "mark_source": source,
                    "freshness": freshness,
                }
            )
            marks.append(
                LivePositionMark(
                    instrument_id=iid,
                    ticker=ticker,
                    quantity=qty,
                    entry_price=entry,
                    mark_price=None,
                    mark_source=source,
                    market_value=None,
                    invested_cost=invested,
                    unrealized_pnl=None,
                    unrealized_pnl_pct=None,
                    freshness=freshness,
                    quote_time=quote_time,
                    priced=False,
                )
            )
            continue
        covered += 1
        mv = qty * price
        known_market_value += mv
        upnl = (mv - invested) if invested is not None else None
        upnl_pct = (upnl / invested) if invested is not None and abs(invested) > 1e-12 else None
        if invested is not None:
            invested_priced += invested
        if upnl is not None:
            partial_unrealized += upnl
            has_partial_upnl = True
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
                priced=True,
            )
        )

    cash_f = float(cash)
    known_nav = cash_f + known_market_value
    coverage = (covered / total) if total else 1.0
    # Value coverage: share of invested cost that is priced (fallback to count coverage).
    if invested_cost_total > 1e-12:
        value_coverage = invested_priced / invested_cost_total
    else:
        value_coverage = coverage

    if total == 0:
        status = ValuationStatus.FULL
        nav: float | None = cash_f
        unrealized: float | None = 0.0 if cost_basis_nav is None else cash_f - float(cost_basis_nav)
        partial_upnl: float | None = None
    elif covered == total:
        status = ValuationStatus.FULL
        nav = known_nav
        if has_partial_upnl:
            unrealized = partial_unrealized
        elif cost_basis_nav is not None:
            unrealized = known_nav - float(cost_basis_nav)
        else:
            unrealized = None
        partial_upnl = None
    elif covered == 0:
        status = ValuationStatus.UNAVAILABLE
        nav = None
        unrealized = None
        partial_upnl = None
        warnings.append("valuation_unavailable:no_marks")
    else:
        status = ValuationStatus.PARTIAL
        nav = None
        unrealized = None
        partial_upnl = partial_unrealized if has_partial_upnl else None
        warnings.append(f"valuation_partial:priced_{covered}_of_{total}")

    unrealized_pct = None
    if unrealized is not None and invested_cost_total > 1e-12:
        unrealized_pct = unrealized / invested_cost_total

    priced_freshness = [str(m.freshness).upper() for m in marks if m.priced]
    marks_as_of: datetime | None = None
    for m in marks:
        if m.priced and m.quote_time is not None:
            if marks_as_of is None or m.quote_time > marks_as_of:
                marks_as_of = m.quote_time
    if total == 0:
        val_freshness = ValuationFreshness.FRESH
    elif not priced_freshness:
        val_freshness = ValuationFreshness.UNAVAILABLE
    else:
        fresh_like = {"LIVE", "FRESH", "DELAYED"}
        stale_like = {"STALE", "PREVIOUS_CLOSE", "MARKET_CLOSED", "SESSION_NOT_STARTED"}
        has_fresh = any(f in fresh_like for f in priced_freshness)
        has_stale = any(f in stale_like or f not in fresh_like for f in priced_freshness)
        # PREVIOUS_CLOSE / EOD fallback already set freshness=STALE on the mark.
        if has_fresh and has_stale:
            val_freshness = ValuationFreshness.MIXED
        elif has_fresh and not has_stale:
            val_freshness = ValuationFreshness.FRESH
        else:
            val_freshness = ValuationFreshness.STALE
        if status == ValuationStatus.FULL and val_freshness == ValuationFreshness.STALE:
            warnings.append("valuation_full_but_stale:not_execution_mark")

    return LivePortfolioSnapshot(
        portfolio_id=portfolio_id,
        cash=cash_f,
        invested_cost=invested_cost_total,
        known_market_value=known_market_value,
        nav=nav,
        known_nav=known_nav,
        valuation_status=status,
        unrealized_pnl=unrealized,
        unrealized_pnl_pct=unrealized_pct,
        partial_unrealized_pnl=partial_upnl,
        position_marks=tuple(marks),
        unpriced_positions=tuple(unpriced),
        as_of=as_of,
        quote_coverage=coverage,
        value_coverage=value_coverage,
        warnings=tuple(warnings),
        valuation_freshness=val_freshness,
        marks_as_of=marks_as_of or as_of,
    )
