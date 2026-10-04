"""Operational recovery helpers for Canonical Evidence Campaign V1.

Does not promote DatasetSpec. Does not rebuild SUCCESS/WARNING runs.
Incomplete RUNNING campaign builds are marked via the official workflow service.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetRun, DatasetSpec
from app.infrastructure.market.models import Workflow
from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_ACTIVE_VERSION,
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_V3_VERSION,
    PIT_DAILY_CORE_V4_VERSION,
)
from app.modules.market.application.workflows import finish_workflow, update_step
from app.modules.research_evidence.campaign_window import PRIMARY_DATE_FROM

INTERRUPT_REASON = "LOCAL_PROCESS_INTERRUPTED_BY_HOST_SHUTDOWN"
REUSABLE_RUN_STATUSES = frozenset({"SUCCESS", "WARNING"})
CAMPAIGN_SPEC_VERSIONS = (PIT_DAILY_CORE_V3_VERSION, PIT_DAILY_CORE_V4_VERSION)


def verify_research_specs(session: Session) -> dict[str, Any]:
    """Require inactive V3/V4 research specs and exactly one active v1 row."""
    if PIT_DAILY_CORE_ACTIVE_VERSION != 1:
        raise ValueError("PIT_DAILY_CORE_ACTIVE_VERSION must remain 1")
    rows = list(
        session.scalars(
            select(DatasetSpec)
            .where(DatasetSpec.code == PIT_DAILY_CORE_CODE)
            .order_by(DatasetSpec.version)
        )
    )
    by_version = {int(spec.version): spec for spec in rows}
    active = [spec for spec in rows if spec.is_active]
    if len(active) != 1 or int(active[0].version) != 1:
        raise ValueError(
            "active pit_daily_core must remain exactly v1 "
            f"(got {[(int(s.version), s.is_active) for s in rows]})"
        )
    missing = [ver for ver in CAMPAIGN_SPEC_VERSIONS if ver not in by_version]
    if missing:
        raise ValueError(f"missing DatasetSpec {PIT_DAILY_CORE_CODE} versions {missing}")
    for ver in CAMPAIGN_SPEC_VERSIONS:
        if by_version[ver].is_active:
            raise ValueError(f"campaign spec v{ver} must stay inactive")
    return {
        "active_version": 1,
        "v3_spec_id": str(by_version[3].id),
        "v4_spec_id": str(by_version[4].id),
        "v4_exists": True,
        "v4_active": False,
    }


def find_reusable_dataset_run(
    session: Session,
    *,
    spec_version: int,
    date_from: date,
    date_to: date,
) -> DatasetRun | None:
    """Return the latest complete campaign DatasetRun for an exact window, or None."""
    if spec_version not in CAMPAIGN_SPEC_VERSIONS:
        return None
    stmt = (
        select(DatasetRun)
        .join(DatasetSpec, DatasetRun.dataset_spec_id == DatasetSpec.id)
        .where(
            DatasetSpec.code == PIT_DAILY_CORE_CODE,
            DatasetSpec.version == spec_version,
            DatasetRun.date_from == date_from,
            DatasetRun.date_to == date_to,
            DatasetRun.status.in_(tuple(REUSABLE_RUN_STATUSES)),
            DatasetRun.pit_status == "PASS",
            DatasetRun.samples_total > 0,
        )
        .order_by(DatasetRun.id.desc())
    )
    return session.scalars(stmt).first()


def interrupt_stale_campaign_dataset_builds(
    session: Session,
    *,
    date_from: date = PRIMARY_DATE_FROM,
    reason: str = INTERRUPT_REASON,
) -> list[dict[str, Any]]:
    """Mark host-interrupted RUNNING v3/v4 campaign builds via finish_workflow.

    Leaves SUCCESS/WARNING runs and the filesystem PIT_FAIL audit untouched.
    Does not touch unrelated Dataset V1/V2 RUNNING rows.
    """
    stmt = (
        select(DatasetRun)
        .join(DatasetSpec, DatasetRun.dataset_spec_id == DatasetSpec.id)
        .where(
            DatasetSpec.code == PIT_DAILY_CORE_CODE,
            DatasetSpec.version.in_(CAMPAIGN_SPEC_VERSIONS),
            DatasetRun.status == "RUNNING",
            DatasetRun.date_from == date_from,
        )
        .order_by(DatasetRun.id)
    )
    touched: list[dict[str, Any]] = []
    for run in session.scalars(stmt):
        spec = session.get(DatasetSpec, run.dataset_spec_id)
        run.status = "ERROR"
        run.error_message = reason
        run.finished_at = datetime.now(UTC)
        workflow = session.get(Workflow, run.workflow_id) if run.workflow_id else None
        if workflow is not None and str(workflow.status).upper() == "RUNNING":
            for step in list(workflow.steps or []):
                if step.status == "RUNNING":
                    update_step(session, step, "ERROR", error=reason)
            try:
                finish_workflow(session, workflow, "ERROR", error=reason)
            except Exception:  # noqa: BLE001 — still persist DatasetRun ERROR
                workflow.status = "ERROR"
                workflow.error = reason
        session.flush()
        touched.append(
            {
                "dataset_run_id": run.id,
                "spec_version": None if spec is None else int(spec.version),
                "workflow_id": run.workflow_id,
                "status": run.status,
                "reason": reason,
            }
        )
    return touched


__all__ = [
    "INTERRUPT_REASON",
    "find_reusable_dataset_run",
    "interrupt_stale_campaign_dataset_builds",
    "verify_research_specs",
]
