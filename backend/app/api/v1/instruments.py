"""Instrument Master catalog APIs (/api/v1/instruments)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.infrastructure.db.session import core_session
from app.modules.market.application.instrument_capabilities import (
    coverage_matrix,
    resolve_instrument_capabilities,
)
from app.modules.market.application.instrument_master_sync import (
    latest_sync_status,
    run_instrument_master_sync,
)
from app.modules.market.application.instrument_search import search_instruments
from app.modules.market.application.research_universe import is_research_member
from app.worker import tasks as worker_tasks

router = APIRouter()


class SyncTriggerResponse(BaseModel):
    status: str
    task_id: str | None = None
    report: dict[str, Any] | None = None


@router.get("")
def list_catalog_instruments(
    search: str | None = None,
    q: str | None = None,
    type: str | None = Query(None, alias="type"),
    asset_class: str | None = None,
    active: bool | None = True,
    support: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> dict[str, Any]:
    query = search or q
    with core_session() as session:
        return search_instruments(
            session,
            q=query,
            asset_class=asset_class,
            instrument_subtype=type,
            active=active,
            support_level=support,
            page=page,
            page_size=page_size,
        )


@router.get("/master/sync/status")
def instrument_master_sync_status() -> dict[str, Any]:
    with core_session() as session:
        latest = latest_sync_status(session)
        if latest is None:
            return {"status": "NONE", "report": None}
        return latest


@router.post("/master/sync")
def trigger_instrument_master_sync(
    async_mode: bool = Query(True, description="Enqueue Celery task when true"),
) -> SyncTriggerResponse:
    if async_mode:
        result = worker_tasks.sync_moex_instrument_master.delay()
        return SyncTriggerResponse(status="SCHEDULED", task_id=getattr(result, "id", None))
    with core_session() as session:
        report = run_instrument_master_sync(session, acquire_lock=True)
        return SyncTriggerResponse(status=str(report.get("status")), report=report)


@router.get("/{id_or_secid}")
def get_catalog_instrument(id_or_secid: str) -> dict[str, Any]:
    from sqlalchemy.orm import selectinload

    from app.infrastructure.market.models import Instrument
    from sqlalchemy import select

    with core_session() as session:
        raw = (id_or_secid or "").strip()
        row = None
        if raw.isdigit():
            row = session.scalar(
                select(Instrument)
                .options(selectinload(Instrument.sources))
                .where(Instrument.id == int(raw))
            )
        else:
            row = session.scalar(
                select(Instrument)
                .options(selectinload(Instrument.sources))
                .where(Instrument.symbol == raw.upper(), Instrument.exchange == "MOEX")
            )
        if row is None:
            raise HTTPException(404, "Instrument not found")
        caps = resolve_instrument_capabilities(session, row)
        member = is_research_member(session, int(row.id))
        return {
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
            "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            "research_member": member,
            "capabilities": caps.to_dict(),
            "coverage": coverage_matrix(caps),
            "sources": [
                {
                    "source": s.source,
                    "external_id": s.external_id,
                    "board": s.board,
                    "valid_from": s.valid_from.isoformat() if s.valid_from else None,
                    "valid_to": s.valid_to.isoformat() if s.valid_to else None,
                }
                for s in (row.sources or [])
            ],
        }
