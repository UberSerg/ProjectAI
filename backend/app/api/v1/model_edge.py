"""Model Edge Research Pack V0 — diagnostics + prospective A/B APIs."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.infrastructure.db.session import core_session
from app.modules.model_edge.application import read_models

router = APIRouter()


@router.get("/model-diagnostics/summary")
def get_diagnostics_summary() -> dict:
    with core_session() as session:
        return read_models.diagnostics_summary(session)


@router.get("/model-diagnostics/top-tail")
def get_diagnostics_top_tail() -> dict:
    with core_session() as session:
        return read_models.diagnostics_top_tail(session)


@router.get("/model-diagnostics/stability")
def get_diagnostics_stability() -> dict:
    with core_session() as session:
        return read_models.diagnostics_stability(session)


@router.get("/model-diagnostics/regimes")
def get_diagnostics_regimes() -> dict:
    with core_session() as session:
        return read_models.diagnostics_regimes(session)


@router.get("/model-diagnostics/disagreements")
def get_diagnostics_disagreements(
    as_of: Annotated[date | None, Query()] = None,
) -> dict:
    with core_session() as session:
        return read_models.diagnostics_disagreements(session, as_of=as_of)


@router.get("/model-diagnostics/economic-viability")
def get_economic_viability(
    annual_rate: Annotated[float, Query(ge=0.0, le=0.30)] = 0.10,
) -> dict:
    with core_session() as session:
        return read_models.diagnostics_economic(session, annual_rate=annual_rate)


@router.get("/model-experiments/prospective/latest")
def get_prospective_latest() -> dict:
    with core_session() as session:
        return read_models.prospective_latest(session)


@router.get("/model-experiments/prospective/batches")
def get_prospective_batches() -> dict:
    with core_session() as session:
        return read_models.prospective_batches(session)


@router.get("/model-experiments/prospective/batches/{batch_id}")
def get_prospective_batch(batch_id: int) -> dict:
    with core_session() as session:
        payload = read_models.prospective_batch_detail(session, batch_id)
        if payload.get("status") == "NOT_FOUND":
            raise HTTPException(status_code=404, detail="comparison batch not found")
        return payload


@router.get("/model-experiments/prospective/evaluation")
def get_prospective_evaluation() -> dict:
    with core_session() as session:
        return read_models.prospective_evaluation(session)
