"""Resolve acceptance instruments from Instrument Master (no hardcoded IDs)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument

DEFAULT_ACCEPTANCE_SYMBOLS: tuple[str, ...] = ("SBER", "LKOH", "MGNT")


def resolve_equity_by_symbol(session: Session, symbol: str) -> Instrument | None:
    stmt = (
        select(Instrument)
        .where(
            Instrument.symbol == symbol,
            Instrument.exchange == "MOEX",
            Instrument.asset_class == "equity",
        )
        .order_by(Instrument.is_active.desc(), Instrument.id.asc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def resolve_acceptance_set(
    session: Session,
    symbols: tuple[str, ...] = DEFAULT_ACCEPTANCE_SYMBOLS,
) -> list[Instrument]:
    found: list[Instrument] = []
    for symbol in symbols:
        row = resolve_equity_by_symbol(session, symbol)
        if row is not None:
            found.append(row)
    return found
