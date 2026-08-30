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
    *,
    trace_id: str | None = None,
) -> Workflow:
    from app.application.system.event_log import new_trace_id, write_event

    tid = trace_id or new_trace_id()
    workflow = Workflow(
        workflow_type=workflow_type,
        name=name,
        status="RUNNING",
        started_at=datetime.now(UTC),
        meta={"completed": 0, "total": len(steps), "trace_id": tid},
    )
    workflow.steps = [WorkflowStep(name=step, status="PENDING") for step in steps]
    session.add(workflow)
    session.flush()
    write_event(
        session,
        level="INFO",
        component="workflow",
        event_type="workflow_started",
        message=f"Workflow started: {name}",
        details={"workflow_type": workflow_type, "name": name},
        workflow_id=workflow.id,
        trace_id=tid,
    )
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
    from app.application.system.event_log import write_event

    workflow.status = status
    workflow.error = error
    workflow.finished_at = datetime.now(UTC)
    session.flush()
    level = "ERROR" if status.upper() in {"ERROR", "FAILED"} else "WARNING" if status.upper() == "WARNING" else "INFO"
    write_event(
        session,
        level=level,  # type: ignore[arg-type]
        component="workflow",
        event_type="workflow_finished" if status.upper() in {"SUCCESS", "WARNING"} else "workflow_failed",
        message=f"Workflow finished: {workflow.name} ({status})",
        details={"status": status, "error": error},
        workflow_id=workflow.id,
        trace_id=(workflow.meta or {}).get("trace_id"),
    )
