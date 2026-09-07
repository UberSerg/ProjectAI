"""Research universe membership helpers (frozen curated seed)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument, UniverseMembership
from app.modules.market.universe import INSTRUMENTS

RESEARCH_EQUITY_V1 = "research_equity_v1"


def research_equity_symbols() -> tuple[str, ...]:
    return tuple(item.symbol for item in INSTRUMENTS if item.asset_class == "equity")


def seed_research_equity_membership(session: Session) -> dict[str, int]:
    """Idempotently seed research_equity_v1 from curated universe.py equities.

    Never called from Instrument Master sync for newly discovered catalog symbols.
    """
    symbols = list(research_equity_symbols())
    if not symbols:
        return {"seeded": 0, "missing_instruments": 0}

    rows = list(
        session.scalars(
            select(Instrument).where(
                Instrument.exchange == "MOEX",
                Instrument.symbol.in_(symbols),
            )
        )
    )
    by_symbol = {r.symbol: r for r in rows}
    seeded = 0
    for symbol in symbols:
        instrument = by_symbol.get(symbol)
        if instrument is None:
            continue
        stmt = insert(UniverseMembership).values(
            universe_code=RESEARCH_EQUITY_V1,
            instrument_id=int(instrument.id),
        )
        session.execute(stmt.on_conflict_do_nothing())
        seeded += 1
    session.flush()
    return {
        "seeded": seeded,
        "missing_instruments": len(symbols) - seeded,
        "universe_code": RESEARCH_EQUITY_V1,
    }


def is_research_member(session: Session, instrument_id: int) -> bool:
    row = session.get(UniverseMembership, (RESEARCH_EQUITY_V1, int(instrument_id)))
    return row is not None


def research_member_ids(session: Session) -> set[int]:
    return set(
        session.scalars(
            select(UniverseMembership.instrument_id).where(
                UniverseMembership.universe_code == RESEARCH_EQUITY_V1
            )
        )
    )
