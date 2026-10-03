"""OWNER research-only Evidence Engine API."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.infrastructure.db.session import core_session, memory_session
from app.infrastructure.learning.models import DatasetRun
from app.modules.market.application.workflows import create_workflow
from app.modules.research_evidence.campaign_runner import (
    CAMPAIGN_WORKFLOW_STEPS,
    PUBLIC_CAMPAIGN_VERSION,
    find_completed_canonical_campaign,
    list_campaign_summaries,
    load_campaign_dossier,
    load_campaign_summary,
)
from app.modules.research_evidence.overview_map import FORBIDDEN_OVERVIEW_KEYS, map_prospective_ui
from app.modules.research_evidence.prospective import build_prospective_evidence_v1
from app.modules.research_evidence.service import get_evidence, get_latest_evidence, resolve_frozen_run_ids
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


class CanonicalCampaignLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_version: str
    exact_rerun: bool = False


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


def _enqueue_evidence_run(
    *,
    experiment_id: str | None,
    v3_run_id: int | None,
    v4_run_id: int | None,
    date_from: date | None,
    date_to: date | None,
    instrument_ids: list[int] | None,
    rebuild: bool,
) -> dict[str, Any]:
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
            v3_run_id,
            v4_run_id,
            date_from.isoformat() if date_from else None,
            date_to.isoformat() if date_to else None,
            instrument_ids,
            rebuild,
        )
        return {
            "status": "RUNNING",
            "message": "Запущен research-only пересчёт. Это не промоушен Candidate.",
            "experiment_id": experiment_id,
            "workflow_id": str(workflow.id),
            "v3_run_id": v3_run_id,
            "v4_run_id": v4_run_id,
        }


@router.post("/run")
def evidence_run(body: EvidenceRunRequest) -> dict[str, Any]:
    """OWNER research run. Frozen experiment IDs only — never a hidden current universe."""
    if body.experiment_id:
        frozen = resolve_frozen_run_ids(body.experiment_id)
        if frozen is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "EXPERIMENT_NOT_FOUND",
                    "message": "Эксперимент доказательств не найден.",
                },
            )
        v3_run_id = frozen["dataset_v3_run_id"]
        v4_run_id = frozen["dataset_v4_run_id"]
        with core_session() as session:
            run_v3 = session.get(DatasetRun, v3_run_id)
            run_v4 = session.get(DatasetRun, v4_run_id)
        if run_v3 is None or run_v4 is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "FROZEN_RUN_MISSING",
                    "message": (
                        "Замороженные DatasetRun эксперимента недоступны "
                        f"(v3={v3_run_id}, v4={v4_run_id}). "
                        "Скрытая текущая вселенная и новое окно не используются."
                    ),
                },
            )
        return _enqueue_evidence_run(
            experiment_id=body.experiment_id,
            v3_run_id=v3_run_id,
            v4_run_id=v4_run_id,
            date_from=None,
            date_to=None,
            instrument_ids=None,
            rebuild=False,
        )

    if body.v3_run_id is None or body.v4_run_id is None:
        if body.date_from is None or body.date_to is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "EXPLICIT_IDS_OR_WINDOW_REQUIRED",
                    "message": (
                        "Нужны v3_run_id и v4_run_id либо явный интервал date_from/date_to. "
                        "Скрытая текущая вселенная не используется."
                    ),
                },
            )
        if body.date_to < body.date_from:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_DATE_WINDOW", "message": "date_to должен быть >= date_from"},
            )
    return _enqueue_evidence_run(
        experiment_id=body.experiment_id,
        v3_run_id=body.v3_run_id,
        v4_run_id=body.v4_run_id,
        date_from=body.date_from,
        date_to=body.date_to,
        instrument_ids=body.instrument_ids,
        rebuild=body.rebuild,
    )


@router.get("/campaigns")
def list_evidence_campaigns() -> dict[str, Any]:
    return list_campaign_summaries()


@router.post("/campaigns/canonical-v1")
def launch_canonical_campaign_v1(body: CanonicalCampaignLaunchRequest) -> dict[str, Any]:
    if body.campaign_version != PUBLIC_CAMPAIGN_VERSION:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNSUPPORTED_CAMPAIGN_VERSION",
                "message": f"Only {PUBLIC_CAMPAIGN_VERSION} can be launched.",
            },
        )
    if not body.exact_rerun:
        existing = find_completed_canonical_campaign()
        if existing is not None:
            return {
                "status": existing.get("status"),
                "message": "Найдена уже завершённая каноническая кампания; повтор не запускался.",
                "fingerprint": existing.get("fingerprint"),
                "campaign_version": PUBLIC_CAMPAIGN_VERSION,
                "existing": True,
                "exact_rerun": False,
            }
    with core_session() as session:
        workflow = create_workflow(
            session,
            PUBLIC_CAMPAIGN_VERSION,
            PUBLIC_CAMPAIGN_VERSION,
            list(CAMPAIGN_WORKFLOW_STEPS),
        )
        session.commit()
        worker_tasks.canonical_evidence_campaign_v1.delay(workflow.id, bool(body.exact_rerun))
        return {
            "status": "RUNNING",
            "message": "Запущена CanonicalEvidenceCampaignV1. Это не промоушен Candidate.",
            "fingerprint": None,
            "campaign_version": PUBLIC_CAMPAIGN_VERSION,
            "existing": False,
            "exact_rerun": bool(body.exact_rerun),
            "workflow_id": str(workflow.id),
        }


@router.get("/campaigns/{fingerprint}/dossier")
def evidence_campaign_dossier(fingerprint: str) -> dict[str, Any]:
    payload = load_campaign_dossier(fingerprint)
    if payload is None:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    return payload


@router.get("/campaigns/{fingerprint}")
def evidence_campaign(fingerprint: str) -> dict[str, Any]:
    payload = load_campaign_summary(fingerprint)
    if payload is None:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    return payload


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
