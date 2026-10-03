"""OWNER research-only Evidence Engine API."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.infrastructure.db.session import core_session, memory_session
from app.modules.market.application.workflows import create_workflow
from app.modules.research_evidence.overview_map import FORBIDDEN_OVERVIEW_KEYS, map_prospective_ui
from app.modules.research_evidence.prospective import build_prospective_evidence_v1
from app.modules.research_evidence.service import get_evidence, get_latest_evidence
from app.worker import tasks as worker_tasks

router = APIRouter()

EVIDENCE_WORKFLOW_STEPS = [
    "Pair datasets",
    "Chronological OOS",
    "Write bundle",
    "Finish",
]


class EvidenceRunRequest(BaseModel):
    experiment_id: str | None = None
    note: str | None = None
    v3_run_id: int | None = None
    v4_run_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    instrument_ids: list[int] | None = None
    rebuild: bool = False


def _strip_forbidden(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    for key in FORBIDDEN_OVERVIEW_KEYS:
        out.pop(key, None)
    return out


@router.get("/overview")
def evidence_overview() -> dict[str, Any]:
    return _strip_forbidden(get_latest_evidence())


@router.get("/prospective")
def evidence_prospective() -> dict[str, Any]:
    try:
        with memory_session() as memory, core_session() as core:
            raw = build_prospective_evidence_v1(memory_session=memory, core_session=core)
        return map_prospective_ui(raw)
    except Exception:  # noqa: BLE001 — read-model must not 500 an empty Memory/Core
        return map_prospective_ui({"status": "PENDING"})


@router.post("/run")
def evidence_run(body: EvidenceRunRequest) -> dict[str, Any]:
    """OWNER research run. Does not block on model training; uses existing Workflow/Celery."""
    if body.v3_run_id is None or body.v4_run_id is None:
        if body.date_from is None or body.date_to is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Нужны v3_run_id и v4_run_id либо явный интервал date_from/date_to. "
                    "Скрытая текущая вселенная не используется."
                ),
            )
        if body.date_to < body.date_from:
            raise HTTPException(status_code=400, detail="date_to должен быть >= date_from")
    with core_session() as session:
        workflow = create_workflow(
            session,
            "ResearchEvidence",
            "Research Evidence Engine V1",
            EVIDENCE_WORKFLOW_STEPS,
        )
        session.commit()
        worker_tasks.research_evidence_run.delay(
            workflow.id,
            body.v3_run_id,
            body.v4_run_id,
            body.date_from.isoformat() if body.date_from else None,
            body.date_to.isoformat() if body.date_to else None,
            body.instrument_ids,
            body.rebuild,
        )
        return {
            "status": "RUNNING",
            "message": "Запущен research-only пересчёт. Это не промоушен Candidate.",
            "experiment_id": body.experiment_id,
            "workflow_id": str(workflow.id),
        }


@router.get("/{experiment_id}/economics")
def evidence_economics(experiment_id: str) -> dict[str, Any]:
    payload = get_evidence(experiment_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Эксперимент не найден")
    return payload.get("economics") or {}


@router.get("/{experiment_id}")
def evidence_experiment(experiment_id: str) -> dict[str, Any]:
    payload = get_evidence(experiment_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Эксперимент не найден")
    return {
        "experiment": payload.get("experiment"),
        "dataset": payload.get("dataset"),
        "historical_models": payload.get("historical_models"),
        "ablation": payload.get("ablation"),
        "stability": payload.get("stability"),
        "limitations": payload.get("limitations"),
    }
