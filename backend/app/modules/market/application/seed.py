"""Idempotently seed the curated market universe."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument, InstrumentSource, Series
from app.modules.market.universe import INSTRUMENTS, SERIES


def seed_market_universe(session: Session) -> dict[str, int]:
    for item in INSTRUMENTS:
        statement = insert(Instrument).values(
            symbol=item.symbol,
            name=item.name,
            asset_class=item.asset_class,
            currency=item.currency,
            exchange=item.exchange,
            is_active=True,
        )
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[Instrument.symbol, Instrument.exchange],
                set_={
                    "name": item.name,
                    "asset_class": item.asset_class,
                    "is_active": True,
                },
            )
        )
    session.flush()

    ids = {
        row.symbol: row.id
        for row in session.scalars(
            select(Instrument).where(Instrument.exchange == "MOEX")
        ).all()
    }
    for item in INSTRUMENTS:
        statement = insert(InstrumentSource).values(
            instrument_id=ids[item.symbol],
            source=item.source,
            external_id=item.symbol,
            board=item.board or "",
            source_metadata={},
        )
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    InstrumentSource.source,
                    InstrumentSource.external_id,
                    InstrumentSource.board,
                ],
                set_={"instrument_id": ids[item.symbol]},
            )
        )

    for item in SERIES:
        statement = insert(Series).values(
            code=item.code,
            name=item.name,
            unit=item.unit,
            source=item.source,
            description=f"external_id={item.external_id}",
            is_active=True,
        )
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[Series.code],
                set_={
                    "name": item.name,
                    "unit": item.unit,
                    "description": f"external_id={item.external_id}",
                    "is_active": True,
                },
            )
        )
    session.flush()
    return {"instruments": len(INSTRUMENTS), "series": len(SERIES)}
