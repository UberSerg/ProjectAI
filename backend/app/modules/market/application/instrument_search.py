"""Instrument catalog search with ILIKE ranking: exact > prefix > contains."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.orm import Session, selectinload

from app.infrastructure.market.models import Instrument


def search_instruments(
    session: Session,
    *,
    q: str | None = None,
    asset_class: str | None = None,
    instrument_subtype: str | None = None,
    active: bool | None = None,
    support_level: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    filters = []
    if active is not None:
        filters.append(Instrument.is_active.is_(active))
    if asset_class:
        filters.append(Instrument.asset_class == asset_class)
    if instrument_subtype:
        filters.append(Instrument.instrument_subtype == instrument_subtype)
    if support_level:
        filters.append(Instrument.support_level == support_level)

    rank_expr = literal(3)
    order_exprs: list[Any] = [Instrument.symbol]
    if q:
        pattern = f"%{q}%"
        prefix = f"{q}%"
        filters.append(
            or_(
                Instrument.symbol.ilike(pattern),
                Instrument.name.ilike(pattern),
                Instrument.isin.ilike(pattern),
            )
        )
        rank_expr = case(
            (func.upper(Instrument.symbol) == q.upper(), 0),
            (Instrument.symbol.ilike(prefix), 1),
            (Instrument.name.ilike(prefix), 2),
            else_=3,
        )
        order_exprs = [rank_expr, Instrument.symbol]

    base = select(Instrument).where(*filters) if filters else select(Instrument)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.scalars(
        base.options(selectinload(Instrument.sources))
        .order_by(*order_exprs)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique().all()

    items = [
        {
            "id": row.id,
            "symbol": row.symbol,
            "name": row.name,
            "asset_class": row.asset_class,
            "instrument_subtype": row.instrument_subtype,
            "support_level": row.support_level,
            "primary_board": row.primary_board,
            "exchange": row.exchange,
            "currency": row.currency,
            "isin": row.isin,
            "is_active": row.is_active,
            "sources": sorted({s.source for s in row.sources}),
        }
        for row in rows
    ]
    return {"items": items, "total": int(total), "page": page, "page_size": page_size}


def resolve_instrument_ref(session: Session, id_or_secid: str) -> Instrument | None:
    raw = (id_or_secid or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return session.get(Instrument, int(raw))
    return session.scalar(
        select(Instrument).where(
            Instrument.symbol == raw.upper(),
            Instrument.exchange == "MOEX",
        )
    )
