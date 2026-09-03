"""Relations Engine API — sets, inputs, runs, snapshots, compute."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select

from app.infrastructure.analytics.relation_models import (
    RelationInput,
    RelationLagMetric,
    RelationRun,
    RelationSet,
    RelationSnapshot,
)
from app.infrastructure.db.session import core_session
from app.modules.market.application.workflows import create_workflow
from app.modules.relations.application.resolve import RelationSetResolveError, resolve_relation_set
from app.modules.relations.application.seed import seed_relation_inputs, seed_relation_sets
from app.modules.relations.relation_config import RELATIONS_COMPUTE_STEPS
from app.worker import tasks as worker_tasks

router = APIRouter()


class RelationSetResponse(BaseModel):
    id: str
    code: str
    version: int
    description: str | None
    parameters: dict[str, Any]
    is_active: bool


class RelationInputResponse(BaseModel):
    id: str
    code: str
    input_family: str
    subject_type: str
    subject_id: str
    feature_key: str
    transform: str
    alignment_policy: str
    display_name: str | None
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class RelationRunResponse(BaseModel):
    id: str
    relation_set_id: str
    relation_set_code: str | None = None
    relation_set_version: int | None = None
    run_type: str
    as_of_from: date | None
    as_of_to: date | None
    cadence: str | None
    started_at: str | None
    finished_at: str | None
    status: str
    inputs_total: int
    pairs_calculated: int
    snapshots_written: int
    snapshots_valid: int
    snapshots_invalid: int
    snapshots_skipped: int
    source_watermark: str | None
    error_message: str | None
    workflow_id: str | None


class RelationSnapshotResponse(BaseModel):
    id: str
    relation_run_id: str
    relation_set_id: str
    relation_set_version: int
    as_of_date: date
    window_observations: int
    input_a_id: str
    input_b_id: str
    input_a_code: str | None = None
    input_b_code: str | None = None
    input_a_display_name: str | None = None
    input_b_display_name: str | None = None
    sample_count: int
    coverage_ratio: float | None
    pearson: float | None
    spearman: float | None
    rolling_corr_mean: float | None
    rolling_corr_std: float | None
    sign_consistency: float | None
    best_leader_input_id: str | None
    best_follower_input_id: str | None
    best_leader_code: str | None = None
    best_follower_code: str | None = None
    best_lag: int | None
    best_lag_pearson: float | None
    best_lag_spearman: float | None
    is_valid: bool
    quality_flags: dict[str, Any]
    calculated_at: str | None


class RelationLagMetricResponse(BaseModel):
    id: str
    snapshot_id: str
    leader_input_id: str
    follower_input_id: str
    leader_code: str | None = None
    follower_code: str | None = None
    lag: int
    pearson: float | None
    spearman: float | None
    sample_count: int
    coverage_ratio: float | None


class RelationsOverview(BaseModel):
    active_relation_set: RelationSetResponse | None
    inputs_active: int
    snapshots_total: int
    latest_as_of_date: date | None
    last_relation_run: RelationRunResponse | None
    quality: dict[str, int]


class ComputeLatestRequest(BaseModel):
    relation_set_code: str = "basic_relations"
    relation_set_version: int = 1


class BackfillRequest(BaseModel):
    as_of_from: date
    as_of_to: date | None = None
    cadence: str = "WEEKLY"
    relation_set_code: str = "basic_relations"
    relation_set_version: int = 1


class WorkflowCreated(BaseModel):
    workflow_id: int
    status: str


def _dec(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _set_dict(row: RelationSet) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "version": row.version,
        "description": row.description,
        "parameters": row.parameters,
        "is_active": row.is_active,
    }


def _input_dict(row: RelationInput) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "input_family": row.input_family,
        "subject_type": row.subject_type,
        "subject_id": str(row.subject_id),
        "feature_key": row.feature_key,
        "transform": row.transform,
        "alignment_policy": row.alignment_policy,
        "display_name": row.display_name,
        "is_active": row.is_active,
        "metadata": row.metadata_ or {},
    }


def _run_dict(row: RelationRun, relation_set: RelationSet | None = None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "relation_set_id": str(row.relation_set_id),
        "relation_set_code": relation_set.code if relation_set else None,
        "relation_set_version": relation_set.version if relation_set else None,
        "run_type": row.run_type,
        "as_of_from": row.as_of_from,
        "as_of_to": row.as_of_to,
        "cadence": row.cadence,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "status": row.status,
        "inputs_total": row.inputs_total,
        "pairs_calculated": row.pairs_calculated,
        "snapshots_written": row.snapshots_written,
        "snapshots_valid": row.snapshots_valid,
        "snapshots_invalid": row.snapshots_invalid,
        "snapshots_skipped": row.snapshots_skipped,
        "source_watermark": row.source_watermark.isoformat() if row.source_watermark else None,
        "error_message": row.error_message,
        "workflow_id": str(row.workflow_id) if row.workflow_id else None,
    }


def _snapshot_dict(
    row: RelationSnapshot,
    inputs: dict[UUID, RelationInput] | None = None,
) -> dict[str, Any]:
    inputs = inputs or {}
    a = inputs.get(row.input_a_id)
    b = inputs.get(row.input_b_id)
    leader = inputs.get(row.best_leader_input_id) if row.best_leader_input_id else None
    follower = inputs.get(row.best_follower_input_id) if row.best_follower_input_id else None
    return {
        "id": str(row.id),
        "relation_run_id": str(row.relation_run_id),
        "relation_set_id": str(row.relation_set_id),
        "relation_set_version": row.relation_set_version,
        "as_of_date": row.as_of_date,
        "window_observations": row.window_observations,
        "input_a_id": str(row.input_a_id),
        "input_b_id": str(row.input_b_id),
        "input_a_code": a.code if a else None,
        "input_b_code": b.code if b else None,
        "input_a_display_name": a.display_name if a else None,
        "input_b_display_name": b.display_name if b else None,
        "sample_count": row.sample_count,
        "coverage_ratio": _dec(row.coverage_ratio),
        "pearson": _dec(row.pearson),
        "spearman": _dec(row.spearman),
        "rolling_corr_mean": _dec(row.rolling_corr_mean),
        "rolling_corr_std": _dec(row.rolling_corr_std),
        "sign_consistency": _dec(row.sign_consistency),
        "best_leader_input_id": str(row.best_leader_input_id) if row.best_leader_input_id else None,
        "best_follower_input_id": str(row.best_follower_input_id) if row.best_follower_input_id else None,
        "best_leader_code": leader.code if leader else None,
        "best_follower_code": follower.code if follower else None,
        "best_lag": row.best_lag,
        "best_lag_pearson": _dec(row.best_lag_pearson),
        "best_lag_spearman": _dec(row.best_lag_spearman),
        "is_valid": row.is_valid,
        "quality_flags": row.quality_flags or {},
        "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
    }


def _lag_dict(row: RelationLagMetric, inputs: dict[UUID, RelationInput] | None = None) -> dict[str, Any]:
    inputs = inputs or {}
    leader = inputs.get(row.leader_input_id)
    follower = inputs.get(row.follower_input_id)
    return {
        "id": str(row.id),
        "snapshot_id": str(row.snapshot_id),
        "leader_input_id": str(row.leader_input_id),
        "follower_input_id": str(row.follower_input_id),
        "leader_code": leader.code if leader else None,
        "follower_code": follower.code if follower else None,
        "lag": row.lag,
        "pearson": _dec(row.pearson),
        "spearman": _dec(row.spearman),
        "sample_count": row.sample_count,
        "coverage_ratio": _dec(row.coverage_ratio),
    }


def _load_inputs_map(session) -> dict[UUID, RelationInput]:
    rows = list(session.scalars(select(RelationInput)))
    return {r.id: r for r in rows}


@router.get("/overview", response_model=RelationsOverview)
def relations_overview(relation_set_version: int | None = None) -> dict[str, Any]:
    with core_session() as session:
        seed_relation_sets(session)
        active = session.scalar(select(RelationSet).where(RelationSet.is_active.is_(True)))
        chosen = active
        if relation_set_version is not None:
            chosen = resolve_relation_set(session, "basic_relations", relation_set_version)
        inputs_active = (
            session.scalar(select(func.count()).select_from(RelationInput).where(RelationInput.is_active.is_(True)))
            or 0
        )
        snap_q = select(func.count()).select_from(RelationSnapshot)
        as_of_q = select(func.max(RelationSnapshot.as_of_date))
        valid_q = select(func.count()).select_from(RelationSnapshot).where(RelationSnapshot.is_valid.is_(True))
        invalid_q = select(func.count()).select_from(RelationSnapshot).where(RelationSnapshot.is_valid.is_(False))
        run_q = select(RelationRun).order_by(desc(RelationRun.created_at)).limit(1)
        if chosen is not None:
            snap_q = snap_q.where(RelationSnapshot.relation_set_id == chosen.id)
            as_of_q = as_of_q.where(RelationSnapshot.relation_set_id == chosen.id)
            valid_q = valid_q.where(RelationSnapshot.relation_set_id == chosen.id)
            invalid_q = invalid_q.where(RelationSnapshot.relation_set_id == chosen.id)
            run_q = run_q.where(RelationRun.relation_set_id == chosen.id)
        snapshots_total = session.scalar(snap_q) or 0
        latest_as_of = session.scalar(as_of_q)
        last_run = session.scalar(run_q)
        valid = session.scalar(valid_q) or 0
        invalid = session.scalar(invalid_q) or 0
        rs = None
        if last_run:
            rs = session.get(RelationSet, last_run.relation_set_id)
        session.commit()
        return {
            "active_relation_set": _set_dict(active) if active else None,
            "inputs_active": int(inputs_active),
            "snapshots_total": int(snapshots_total),
            "latest_as_of_date": latest_as_of,
            "last_relation_run": _run_dict(last_run, rs) if last_run else None,
            "quality": {"valid": int(valid), "invalid": int(invalid)},
        }


@router.get("/sets", response_model=dict)
def list_relation_sets() -> dict[str, Any]:
    with core_session() as session:
        seed_relation_sets(session)
        rows = list(session.scalars(select(RelationSet).order_by(RelationSet.code, RelationSet.version)))
        session.commit()
        return {"items": [_set_dict(r) for r in rows], "total": len(rows)}


@router.get("/inputs", response_model=dict)
def list_relation_inputs(
    active_only: bool = Query(True),
    family: str | None = Query(None),
) -> dict[str, Any]:
    with core_session() as session:
        seed_relation_inputs(session)
        q = select(RelationInput).order_by(RelationInput.code)
        if active_only:
            q = q.where(RelationInput.is_active.is_(True))
        if family:
            q = q.where(RelationInput.input_family == family)
        rows = list(session.scalars(q))
        session.commit()
        return {"items": [_input_dict(r) for r in rows], "total": len(rows)}


@router.get("/runs", response_model=dict)
def list_relation_runs(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    with core_session() as session:
        rows = list(session.scalars(select(RelationRun).order_by(desc(RelationRun.created_at)).limit(limit)))
        sets = {s.id: s for s in session.scalars(select(RelationSet))}
        return {"items": [_run_dict(r, sets.get(r.relation_set_id)) for r in rows], "total": len(rows)}


@router.get("/runs/{run_id}", response_model=RelationRunResponse)
def get_relation_run(run_id: int) -> dict[str, Any]:
    with core_session() as session:
        row = session.get(RelationRun, run_id)
        if row is None:
            raise HTTPException(404, "Relation run not found")
        rs = session.get(RelationSet, row.relation_set_id)
        return _run_dict(row, rs)


@router.get("/snapshots", response_model=dict)
def list_snapshots(
    as_of_date: date | None = None,
    window: int | None = None,
    min_abs_corr: float | None = Query(None, ge=0, le=1),
    sign: str | None = Query(None, pattern="^(positive|negative|all)?$"),
    valid_only: bool = True,
    search: str | None = None,
    input_a_id: UUID | None = None,
    input_b_id: UUID | None = None,
    relation_set_code: str = "basic_relations",
    relation_set_version: int | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    with core_session() as session:
        inputs_map = _load_inputs_map(session)
        q = select(RelationSnapshot)
        try:
            relation_set = resolve_relation_set(session, relation_set_code, relation_set_version)
        except RelationSetResolveError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        q = q.where(RelationSnapshot.relation_set_id == relation_set.id)
        if as_of_date is not None:
            q = q.where(RelationSnapshot.as_of_date == as_of_date)
        else:
            latest = session.scalar(
                select(func.max(RelationSnapshot.as_of_date)).where(
                    RelationSnapshot.relation_set_id == relation_set.id
                )
            )
            if latest is not None:
                q = q.where(RelationSnapshot.as_of_date == latest)
        if window is not None:
            q = q.where(RelationSnapshot.window_observations == window)
        if valid_only:
            q = q.where(RelationSnapshot.is_valid.is_(True))
        if input_a_id and input_b_id:
            a, b = (input_a_id, input_b_id) if input_a_id < input_b_id else (input_b_id, input_a_id)
            q = q.where(RelationSnapshot.input_a_id == a, RelationSnapshot.input_b_id == b)
        elif input_a_id:
            q = q.where(
                or_(RelationSnapshot.input_a_id == input_a_id, RelationSnapshot.input_b_id == input_a_id)
            )

        rows = list(session.scalars(q.order_by(desc(RelationSnapshot.as_of_date)).limit(2000)))
        items = [_snapshot_dict(r, inputs_map) for r in rows]

        if min_abs_corr is not None:
            items = [
                it
                for it in items
                if it["pearson"] is not None and abs(it["pearson"]) >= min_abs_corr
            ]
        if sign == "positive":
            items = [it for it in items if it["pearson"] is not None and it["pearson"] > 0]
        elif sign == "negative":
            items = [it for it in items if it["pearson"] is not None and it["pearson"] < 0]
        if search:
            needle = search.lower()
            items = [
                it
                for it in items
                if needle in (it["input_a_code"] or "").lower()
                or needle in (it["input_b_code"] or "").lower()
                or needle in (it["input_a_display_name"] or "").lower()
                or needle in (it["input_b_display_name"] or "").lower()
            ]

        items.sort(key=lambda it: abs(it["pearson"] or 0), reverse=True)
        total = len(items)
        page = items[offset : offset + limit]
        return {"items": page, "total": total}


@router.get("/snapshots/{snapshot_id}", response_model=RelationSnapshotResponse)
def get_snapshot(snapshot_id: int) -> dict[str, Any]:
    with core_session() as session:
        row = session.get(RelationSnapshot, snapshot_id)
        if row is None:
            raise HTTPException(404, "Snapshot not found")
        return _snapshot_dict(row, _load_inputs_map(session))


@router.get("/snapshots/{snapshot_id}/lags", response_model=dict)
def get_snapshot_lags(snapshot_id: int) -> dict[str, Any]:
    with core_session() as session:
        snap = session.get(RelationSnapshot, snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        inputs_map = _load_inputs_map(session)
        lags = list(
            session.scalars(
                select(RelationLagMetric)
                .where(RelationLagMetric.snapshot_id == snapshot_id)
                .order_by(RelationLagMetric.lag, RelationLagMetric.leader_input_id)
            )
        )
        return {
            "snapshot": _snapshot_dict(snap, inputs_map),
            "items": [_lag_dict(r, inputs_map) for r in lags],
            "total": len(lags),
            "disclaimer": (
                "Statistical lead/lag is not causation. "
                "leader(t) is correlated with follower(t+lag); this does not imply causality."
            ),
        }


@router.get("/pairs/detail", response_model=dict)
def get_pair_detail(
    input_a_id: UUID,
    input_b_id: UUID,
    as_of_date: date | None = None,
    window: int = Query(60),
    relation_set_code: str = "basic_relations",
    relation_set_version: int | None = None,
) -> dict[str, Any]:
    """Single pair detail with lag profile — avoids N+1 client fetches."""
    with core_session() as session:
        try:
            relation_set = resolve_relation_set(session, relation_set_code, relation_set_version)
        except RelationSetResolveError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        a, b = (input_a_id, input_b_id) if input_a_id < input_b_id else (input_b_id, input_a_id)
        q = select(RelationSnapshot).where(
            RelationSnapshot.relation_set_id == relation_set.id,
            RelationSnapshot.input_a_id == a,
            RelationSnapshot.input_b_id == b,
            RelationSnapshot.window_observations == window,
        )
        if as_of_date is not None:
            q = q.where(RelationSnapshot.as_of_date == as_of_date)
        else:
            q = q.order_by(desc(RelationSnapshot.as_of_date))
        snap = session.scalars(q.limit(1)).first()
        if snap is None:
            raise HTTPException(404, "Pair snapshot not found")
        inputs_map = _load_inputs_map(session)
        lags = list(
            session.scalars(
                select(RelationLagMetric)
                .where(RelationLagMetric.snapshot_id == snap.id)
                .order_by(RelationLagMetric.lag, RelationLagMetric.leader_input_id)
            )
        )
        return {
            "snapshot": _snapshot_dict(snap, inputs_map),
            "lags": [_lag_dict(r, inputs_map) for r in lags],
            "disclaimer": (
                "Statistical lead/lag is not causation. "
                "leader(t) vs follower(t+lag) measures temporal association only."
            ),
        }


@router.post("/compute-latest", response_model=WorkflowCreated)
def start_compute_latest(body: ComputeLatestRequest | None = None) -> dict[str, Any]:
    body = body or ComputeLatestRequest()
    with core_session() as session:
        try:
            resolve_relation_set(session, body.relation_set_code, body.relation_set_version)
        except RelationSetResolveError:
            seed_relation_sets(session)
            try:
                resolve_relation_set(session, body.relation_set_code, body.relation_set_version)
            except RelationSetResolveError as exc2:
                raise HTTPException(exc2.status_code, exc2.message) from exc2
        workflow = create_workflow(
            session,
            "RelationsComputeLatest",
            "Relations compute latest",
            RELATIONS_COMPUTE_STEPS,
        )
        session.commit()
        worker_tasks.relations_compute_latest.delay(
            workflow.id,
            body.relation_set_code,
            body.relation_set_version,
        )
        return {"workflow_id": workflow.id, "status": "RUNNING"}


@router.post("/backfill", response_model=WorkflowCreated)
def start_backfill(body: BackfillRequest) -> dict[str, Any]:
    cadence = body.cadence.upper()
    if cadence not in {"DAILY", "WEEKLY"}:
        raise HTTPException(400, "cadence must be DAILY or WEEKLY")
    with core_session() as session:
        seed_relation_sets(session)
        try:
            resolve_relation_set(session, body.relation_set_code, body.relation_set_version)
        except RelationSetResolveError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        workflow = create_workflow(
            session,
            "RelationsBackfill",
            f"Relations backfill {body.as_of_from} → {body.as_of_to or 'latest'}",
            RELATIONS_COMPUTE_STEPS,
        )
        session.commit()
        worker_tasks.relations_backfill.delay(
            workflow.id,
            body.as_of_from.isoformat(),
            body.as_of_to.isoformat() if body.as_of_to else None,
            cadence,
            body.relation_set_code,
            body.relation_set_version,
        )
        return {"workflow_id": workflow.id, "status": "RUNNING"}
