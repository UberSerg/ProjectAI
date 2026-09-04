"""Research Cycle API — Daily Research Cycle V0 status and control."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.infrastructure.db.session import core_session
from app.infrastructure.market.models import Workflow
from app.modules.market.application.workflows import create_workflow
from app.modules.research_cycle.config import CYCLE_NAME, CYCLE_STEPS, CYCLE_WORKFLOW_TYPE
from app.modules.research_cycle.watermarks import build_operational_status
from app.worker import tasks as worker_tasks

router = APIRouter()


def _serialize_workflow(wf: Workflow) -> dict[str, Any]:
    meta = wf.meta or {}
    return {
        "id": str(wf.id),
        "name": wf.name,
        "workflow_type": wf.workflow_type,
        "status": wf.status,
        "started_at": wf.started_at.isoformat() if wf.started_at else None,
        "finished_at": wf.finished_at.isoformat() if wf.finished_at else None,
        "error": wf.error,
        "meta": meta,
        "steps": [
            {
                "name": s.name,
                "status": s.status,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                "error": s.error,
            }
            for s in (wf.steps or [])
        ],
    }


@router.get("/status")
def research_cycle_status() -> dict[str, Any]:
    with core_session() as db:
        return build_operational_status(db)


@router.get("/latest")
def research_cycle_latest() -> dict[str, Any]:
    with core_session() as db:
        wf = db.scalar(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .where(Workflow.workflow_type == CYCLE_WORKFLOW_TYPE)
            .order_by(Workflow.id.desc())
        )
        if wf is None:
            return {"run": None, "operational": build_operational_status(db)}
        return {"run": _serialize_workflow(wf), "operational": build_operational_status(db)}


@router.get("/runs")
def research_cycle_runs(limit: int = 20) -> dict[str, Any]:
    with core_session() as db:
        rows = list(
            db.scalars(
                select(Workflow)
                .options(selectinload(Workflow.steps))
                .where(Workflow.workflow_type == CYCLE_WORKFLOW_TYPE)
                .order_by(Workflow.id.desc())
                .limit(max(1, min(limit, 100)))
            ).all()
        )
        return {"items": [_serialize_workflow(r) for r in rows]}


@router.get("/runs/{run_id}")
def research_cycle_run(run_id: int) -> dict[str, Any]:
    with core_session() as db:
        wf = db.scalar(
            select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.id == run_id)
        )
        if wf is None or wf.workflow_type != CYCLE_WORKFLOW_TYPE:
            raise HTTPException(status_code=404, detail="Research cycle run not found")
        return _serialize_workflow(wf)


@router.post("/run")
def research_cycle_run_start() -> dict[str, Any]:
    """Controlled operator start — mirrors Processes pattern."""
    with core_session() as db:
        running = db.scalar(
            select(Workflow).where(
                Workflow.workflow_type == CYCLE_WORKFLOW_TYPE,
                Workflow.status == "RUNNING",
            )
        )
        if running is not None:
            raise HTTPException(status_code=409, detail="ALREADY_RUNNING")
        workflow = create_workflow(db, CYCLE_WORKFLOW_TYPE, CYCLE_NAME, CYCLE_STEPS)
        db.commit()
        worker_tasks.daily_research_cycle.delay(workflow.id)
        return {"workflow_id": workflow.id, "status": "RUNNING"}
