"""Read-only API for External Deep History V0 staging."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.infrastructure.db.session import core_session
from app.modules.market_history.application import read_models

router = APIRouter()


@router.get("/status")
def external_status() -> dict[str, Any]:
    with core_session() as session:
        return read_models.status_payload(session)


@router.get("/summary")
def external_summary() -> dict[str, Any]:
    with core_session() as session:
        return read_models.summary_payload(session)


@router.get("/instruments")
def external_instruments(
    match_status: str | None = None,
    research_eligible: bool | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    with core_session() as session:
        return read_models.instruments_payload(
            session,
            match_status=match_status,
            research_eligible=research_eligible,
            limit=limit,
            offset=offset,
        )


@router.get("/coverage")
def external_coverage() -> dict[str, Any]:
    with core_session() as session:
        return read_models.coverage_payload(session)


@router.get("/reconciliation")
def external_reconciliation(limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    with core_session() as session:
        return read_models.reconciliation_payload(session, limit=limit)


@router.get("/ml-readiness")
def external_ml_readiness() -> dict[str, Any]:
    with core_session() as session:
        return read_models.ml_readiness_payload(session)


@router.get("/ca-probes")
def external_ca_probes() -> dict[str, Any]:
    with core_session() as session:
        return read_models.ca_probes_payload(session)
