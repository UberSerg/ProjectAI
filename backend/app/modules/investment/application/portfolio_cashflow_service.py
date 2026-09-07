"""Portfolio Cashflow Intelligence V1 — application layer."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.investment.domain.cashflow_timeline import (
    build_instrument_timeline,
    project_portfolio_cashflows,
)
from app.modules.investment.infrastructure.models import BondCashflow, BondTerm
from app.modules.portfolio.application.manual_portfolio_service import get_or_create_primary


def _load_cashflow_rows(
    session: Session, instrument_id: int
) -> list[tuple[date, str, Decimal | None, str | None]]:
    rows = session.execute(
        select(
            BondCashflow.cashflow_date,
            BondCashflow.cashflow_type,
            BondCashflow.amount,
            BondCashflow.currency,
        )
        .where(BondCashflow.instrument_id == instrument_id)
        .order_by(BondCashflow.cashflow_date)
    ).all()
    return [(r[0], str(r[1]), r[2], r[3]) for r in rows]


def build_manual_portfolio_cashflows(
    session: Session,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    portfolio = get_or_create_primary(session)
    events = []
    per_position: list[dict[str, Any]] = []
    maturity_ladder: dict[str, int] = {"<1y": 0, "1-3y": 0, "3-5y": 0, "5y+": 0, "unknown": 0}
    gov = 0
    corp = 0

    for pos in portfolio.positions or []:
        instrument = session.get(Instrument, pos.instrument_id)
        if instrument is None or (instrument.asset_class or "").lower() != "bond":
            continue
        units = Decimal(str(pos.units))
        cfs = _load_cashflow_rows(session, int(instrument.id))
        timeline = build_instrument_timeline(
            instrument_id=int(instrument.id),
            symbol=instrument.symbol,
            units=units,
            cashflows=cfs,
            as_of=as_of,
        )
        events.extend(timeline)
        next_ev = next(
            (e for e in timeline if not e.informational and e.gross_amount is not None),
            None,
        )
        term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument.id))
        bond_type = term.bond_type if term else None
        if bond_type == "GOVERNMENT":
            gov += 1
        elif bond_type:
            corp += 1
        if term and term.maturity_date:
            days = (term.maturity_date - as_of).days
            if days < 365:
                maturity_ladder["<1y"] += 1
            elif days < 365 * 3:
                maturity_ladder["1-3y"] += 1
            elif days < 365 * 5:
                maturity_ladder["3-5y"] += 1
            else:
                maturity_ladder["5y+"] += 1
        else:
            maturity_ladder["unknown"] += 1

        enrichment_pending = False
        try:
            from app.infrastructure.market.models import InstrumentEnrichmentJob
            from app.modules.investment.domain.enrichment import EnrichmentStatus

            pending = session.scalar(
                select(InstrumentEnrichmentJob.id).where(
                    InstrumentEnrichmentJob.instrument_id == instrument.id,
                    InstrumentEnrichmentJob.status.in_(
                        [EnrichmentStatus.PENDING.value, EnrichmentStatus.RUNNING.value]
                    ),
                )
            )
            enrichment_pending = pending is not None
        except Exception:  # noqa: BLE001
            enrichment_pending = False

        per_position.append(
            {
                "instrument_id": instrument.id,
                "symbol": instrument.symbol,
                "units": float(units),
                "bond_type": bond_type,
                "maturity_date": term.maturity_date.isoformat() if term and term.maturity_date else None,
                "cashflow_count": len(cfs),
                "next_payment": next_ev.to_dict() if next_ev else None,
                "enrichment_pending": enrichment_pending,
                "missing_terms": term is None,
            }
        )

    projection = project_portfolio_cashflows(events=events, as_of=as_of)
    return {
        **projection,
        "portfolio_id": portfolio.id,
        "positions": per_position,
        "analysis": {
            "maturity_ladder": maturity_ladder,
            "gov_vs_corp": {"government": gov, "corporate_or_other": corp},
            "bond_position_count": len(per_position),
        },
    }
