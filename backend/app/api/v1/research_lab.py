"""Simulator Research Lab V0 API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.infrastructure.db.session import core_session
from app.modules.research_lab.application.compare import compare_runs
from app.modules.research_lab.application.service import (
    get_research_run,
    launch_research_run,
    list_research_runs,
    plan_quick_suite,
    research_options,
    run_quick_suite,
)
from app.modules.research_lab.errors import ResearchLabError

router = APIRouter()


class LaunchRequest(BaseModel):
    candidate_id: str = "prediction_ml_candidate/v0"
    segment: str = "DEVELOPMENT_OOS"
    policy_id: str
    risk_id: str
    commission_bps: float = 10.0
    slippage_bps: float = 0.0
    date_from: str | None = None
    date_to: str | None = None
    initial_capital: float = 1_000_000.0
    name: str | None = None
    note: str | None = None
    force_rerun: bool = False


class SuiteRequest(BaseModel):
    candidate_id: str = "prediction_ml_candidate/v0"
    date_from: str | None = None
    date_to: str | None = None
    initial_capital: float = 1_000_000.0


def _http_error(exc: ResearchLabError) -> HTTPException:
    status = 400
    if exc.code in {"RUN_NOT_FOUND"}:
        status = 404
    if exc.code in {"HOLDOUT_LAUNCH_FORBIDDEN"}:
        status = 403
    return HTTPException(status_code=status, detail=exc.to_dict())


@router.get("/options")
def api_options() -> dict:
    return research_options()


@router.get("/runs")
def api_list_runs(
    limit: int = Query(100, ge=1, le=200),
    policy_id: str | None = None,
    risk_id: str | None = None,
    status: str | None = None,
    segment: str | None = None,
    commission_bps: float | None = None,
    sort: str = Query("newest"),
) -> dict:
    with core_session() as session:
        items = list_research_runs(
            session,
            limit=limit,
            policy_id=policy_id,
            risk_id=risk_id,
            status=status,
            segment=segment,
            commission_bps=commission_bps,
            sort=sort,
        )
        return {"items": items}


@router.get("/runs/{run_id}")
def api_get_run(run_id: int) -> dict:
    try:
        with core_session() as session:
            return get_research_run(session, run_id)
    except ResearchLabError as exc:
        raise _http_error(exc) from exc


@router.post("/runs")
def api_launch_run(body: LaunchRequest) -> dict:
    try:
        with core_session() as session:
            out = launch_research_run(session, body.model_dump())
            session.commit()
            return out
    except ResearchLabError as exc:
        raise _http_error(exc) from exc


@router.get("/compare")
def api_compare(run_ids: str = Query(..., description="Comma-separated run ids")) -> dict:
    try:
        ids = [int(x.strip()) for x in run_ids.split(",") if x.strip()]
        with core_session() as session:
            return compare_runs(session, ids)
    except ResearchLabError as exc:
        raise _http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_RUN_IDS", "message": "Некорректный список run_ids"},
        ) from exc


@router.post("/suites/plan")
def api_suite_plan(body: SuiteRequest) -> dict:
    try:
        with core_session() as session:
            return plan_quick_suite(session, body.model_dump())
    except ResearchLabError as exc:
        raise _http_error(exc) from exc


@router.post("/suites")
def api_suite_run(body: SuiteRequest) -> dict:
    try:
        with core_session() as session:
            out = run_quick_suite(session, body.model_dump())
            session.commit()
            return out
    except ResearchLabError as exc:
        raise _http_error(exc) from exc
