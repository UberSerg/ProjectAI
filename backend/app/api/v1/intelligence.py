"""Company Intelligence API — OWNER aggregate + subresources (advisory / research)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.db.session import core_session
from app.infrastructure.market.models import Instrument
from app.modules.intelligence.application.snapshot_builder import (
    IntelligenceSnapshotBuilder,
    build_intelligence_snapshot,
)
from app.modules.intelligence.isolation import production_isolation_report

router = APIRouter()


class RefreshRequest(BaseModel):
    as_of: date | None = None
    force: bool = False
    note: str | None = Field(default=None, max_length=500)


def _get_instrument_or_404(session: Any, instrument_id: int) -> Instrument:
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"instrument {instrument_id} not found")
    return instrument


def _build_snapshot(
    instrument: Instrument,
    as_of: date | None,
    *,
    session: Any | None = None,
) -> dict[str, Any]:
    snap = build_intelligence_snapshot(
        instrument=instrument,
        instrument_id=int(instrument.id),
        as_of=as_of,
        session=session,
    )
    return snap.to_dict()


@router.get("/instruments/{instrument_id}")
def get_intelligence_snapshot(
    instrument_id: int,
    as_of: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    """Aggregate IntelligenceSnapshotV1 for one instrument at as_of."""
    with core_session() as session:
        instrument = _get_instrument_or_404(session, instrument_id)
        return _build_snapshot(instrument, as_of, session=session)


@router.get("/instruments/{instrument_id}/signals")
def get_intelligence_signals(
    instrument_id: int,
    as_of: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    with core_session() as session:
        instrument = _get_instrument_or_404(session, instrument_id)
        snap = IntelligenceSnapshotBuilder().build(
            instrument=instrument,
            instrument_id=int(instrument.id),
            as_of=as_of,
            session=session,
        )
        return {
            "instrument_id": int(instrument.id),
            "symbol": instrument.symbol,
            "as_of": snap.as_of.isoformat() if snap.as_of else None,
            "signals": [s.to_dict() for s in snap.signals],
            "limitations": list(snap.limitations),
        }


@router.get("/instruments/{instrument_id}/events")
def get_intelligence_events(
    instrument_id: int,
    as_of: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    with core_session() as session:
        instrument = _get_instrument_or_404(session, instrument_id)
        snap = IntelligenceSnapshotBuilder().build(
            instrument=instrument,
            instrument_id=int(instrument.id),
            as_of=as_of,
            session=session,
        )
        return {
            "instrument_id": int(instrument.id),
            "symbol": instrument.symbol,
            "as_of": snap.as_of.isoformat() if snap.as_of else None,
            "recent_events": list(snap.recent_events),
            "coverage_status": next(
                (c.status for c in snap.coverage if c.domain == "events"),
                "UNKNOWN",
            ),
            "limitations": ("news_historical_eligibility_requires_trusted_published_at",),
        }


@router.get("/instruments/{instrument_id}/fundamentals")
def get_intelligence_fundamentals(
    instrument_id: int,
    as_of: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    with core_session() as session:
        instrument = _get_instrument_or_404(session, instrument_id)
        snap = IntelligenceSnapshotBuilder().build(
            instrument=instrument,
            instrument_id=int(instrument.id),
            as_of=as_of,
            session=session,
        )
        return {
            "instrument_id": int(instrument.id),
            "symbol": instrument.symbol,
            "as_of": snap.as_of.isoformat() if snap.as_of else None,
            "fundamentals_summary": dict(snap.fundamentals_summary),
        }


@router.get("/instruments/{instrument_id}/committee")
def get_intelligence_committee(
    instrument_id: int,
    as_of: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    with core_session() as session:
        instrument = _get_instrument_or_404(session, instrument_id)
        snap = IntelligenceSnapshotBuilder().build(
            instrument=instrument,
            instrument_id=int(instrument.id),
            as_of=as_of,
            session=session,
        )
        return {
            "instrument_id": int(instrument.id),
            "symbol": instrument.symbol,
            "as_of": snap.as_of.isoformat() if snap.as_of else None,
            "committee": snap.committee.to_dict() if snap.committee else None,
            "what_would_change_decision": (
                list(snap.committee.what_would_change_decision) if snap.committee else []
            ),
        }


@router.post("/instruments/{instrument_id}/refresh")
def refresh_intelligence(
    instrument_id: int,
    body: RefreshRequest | None = None,
) -> dict[str, Any]:
    """OWNER on-demand IntelligenceRefreshV1. ``force`` enables live source fetch."""
    payload = body or RefreshRequest()
    from app.modules.intelligence.operations.refresh import run_intelligence_refresh

    with core_session() as session:
        instrument = _get_instrument_or_404(session, instrument_id)
        result = run_intelligence_refresh(
            session,
            instrument_ids=[int(instrument.id)],
            as_of=payload.as_of.isoformat() if payload.as_of else None,
            force=payload.force,
            dry_run=not payload.force,
            skip_lock=True,
        )
        result["accepted"] = result.get("status") not in {"BLOCKED", "FAILED"}
        result["instrument_id"] = int(instrument.id)
        result["symbol"] = instrument.symbol
        result["force"] = payload.force
        result["production_isolation"] = production_isolation_report()
        return result
