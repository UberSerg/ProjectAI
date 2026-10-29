"""Portfolio Hub card valuations — market marks without ledger rebuild.

Keeps ``list_user_portfolios`` cheap. Hub cards call this batch read-model once
for the visible set: one positions query, one instrument load, one quote batch.
Does not mutate cash, positions, or the operations journal.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.market.application.intraday_cache import IntradayQuoteCache
from app.modules.market.application.operational_quote import ensure_operational_quotes
from app.modules.portfolio.application.personal_portfolio_service import (
    _personal_mark,
    _valuation_label,
)
from app.modules.portfolio.domain.personal_ledger import ZERO, money
from app.modules.portfolio.infrastructure.models import ManualPortfolio, ManualPosition


def build_hub_valuations(
    session: Session,
    *,
    portfolio_ids: list[int] | None = None,
    include_test: bool = False,
) -> list[dict[str, Any]]:
    """Return per-portfolio hub valuation cards (order preserved by ids / updated_at)."""
    q = select(ManualPortfolio)
    if portfolio_ids is not None:
        if not portfolio_ids:
            return []
        q = q.where(ManualPortfolio.id.in_([int(i) for i in portfolio_ids]))
    elif not include_test:
        q = q.where(ManualPortfolio.is_test.is_(False))
    q = q.order_by(ManualPortfolio.updated_at.desc().nullslast(), ManualPortfolio.id.desc())
    portfolios = list(session.scalars(q).all())
    if not portfolios:
        return []

    ids = [int(p.id) for p in portfolios]
    positions = list(
        session.scalars(select(ManualPosition).where(ManualPosition.portfolio_id.in_(ids))).all()
    )
    by_portfolio: dict[int, list[ManualPosition]] = {i: [] for i in ids}
    instrument_ids = {int(pos.instrument_id) for pos in positions}
    for pos in positions:
        by_portfolio.setdefault(int(pos.portfolio_id), []).append(pos)

    instruments_by_id: dict[int, Instrument] = {}
    if instrument_ids:
        for inst in session.scalars(select(Instrument).where(Instrument.id.in_(instrument_ids))):
            instruments_by_id[int(inst.id)] = inst

    equity_fund: list[Instrument] = []
    for inst in instruments_by_id.values():
        asset = (inst.asset_class or "").lower()
        if asset in {"equity", "fund", ""}:
            equity_fund.append(inst)

    quote_cache = IntradayQuoteCache()
    if equity_fund:
        ensure_operational_quotes(session, equity_fund, cache=quote_cache)

    out: list[dict[str, Any]] = []
    for book in portfolios:
        pid = int(book.id)
        cash = money(book.cash_rub or ZERO)
        securities_mv = ZERO
        missing_prices = 0
        price_dates: list[str] = []
        priced_positions = 0
        open_positions = 0

        for pos in by_portfolio.get(pid, []):
            units = Decimal(str(pos.units or 0))
            if abs(units) < Decimal("1e-12"):
                continue
            open_positions += 1
            instrument = instruments_by_id.get(int(pos.instrument_id))
            if instrument is None:
                missing_prices += 1
                continue
            unit_price, market_value, price_date, _asset, _src, _code = _personal_mark(
                session,
                instrument,
                units,
                cache=quote_cache,
                allow_fetch=False,
            )
            if unit_price is not None and market_value is not None:
                securities_mv = money(securities_mv + market_value)
                priced_positions += 1
                if price_date:
                    price_dates.append(price_date)
            else:
                missing_prices += 1

        known_nav = money(cash + securities_mv)
        valuation_complete = missing_prices == 0
        valuation_partial = missing_prices > 0 and open_positions > 0
        # Full NAV only when every open position is priced (cash-only ⇒ complete).
        total_nav: Decimal | None = known_nav if valuation_complete else None
        as_of_from = min(price_dates) if price_dates else None
        as_of_to = max(price_dates) if price_dates else None
        valuation_as_of = (
            as_of_to
            if valuation_complete and as_of_from is not None and as_of_from == as_of_to
            else None
        )
        if open_positions == 0:
            # Cash-only: known_nav == cash is the authoritative total.
            label = "Только денежные средства"
        else:
            label = _valuation_label(price_dates=price_dates, missing_prices=missing_prices)

        out.append(
            {
                "portfolio_id": pid,
                "cash_rub": str(cash),
                "securities_value_rub": str(securities_mv),
                "known_nav_rub": str(known_nav),
                "total_nav_rub": str(total_nav) if total_nav is not None else None,
                "valuation_complete": valuation_complete,
                "valuation_partial": valuation_partial,
                "valuation_unavailable": open_positions > 0 and priced_positions == 0,
                "valuation_as_of": valuation_as_of,
                "valuation_from": as_of_from,
                "valuation_to": as_of_to,
                "valuation_label": label,
                "missing_price_count": missing_prices,
                "positions_count": open_positions,
                "error": None,
            }
        )
    return out


__all__ = ["build_hub_valuations"]
