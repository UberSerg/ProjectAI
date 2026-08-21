"""Operational workflow state transitions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.infrastructure.market.models import Workflow, WorkflowStep

TERMINAL = {"SUCCESS", "WARNING", "ERROR", "success", "warning", "error"}


def create_workflow(
    session: Session,
    workflow_type: str,
    name: str,
    steps: list[str],
) -> Workflow:
    workflow = Workflow(
        workflow_type=workflow_type,
        name=name,
        status="RUNNING",
        started_at=datetime.now(UTC),
        meta={"completed": 0, "total": len(steps)},
    )
    workflow.steps = [WorkflowStep(name=step, status="PENDING") for step in steps]
    session.add(workflow)
    session.flush()
    return workflow


def get_step(workflow: Workflow, name: str) -> WorkflowStep:
    for step in workflow.steps:
        if step.name == name:
            return step
    raise KeyError(name)


def update_step(
    session: Session,
    step: WorkflowStep,
    status: str,
    *,
    error: str | None = None,
) -> None:
    now = datetime.now(UTC)
    if status == "RUNNING" and step.started_at is None:
        step.started_at = now
    if status in TERMINAL:
        step.finished_at = now
    step.status = status
    step.error = error
    workflow = step.workflow
    completed = sum(1 for item in workflow.steps if item.status in TERMINAL)
    workflow.meta = {**(workflow.meta or {}), "completed": completed, "total": len(workflow.steps)}
    session.flush()


def finish_workflow(
    session: Session,
    workflow: Workflow,
    status: str,
    *,
    error: str | None = None,
) -> None:
    workflow.status = status
    workflow.error = error
    workflow.finished_at = datetime.now(UTC)
    session.flush()
