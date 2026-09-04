"""Learning / Dataset PIT API."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from app.infrastructure.db.session import core_session
from app.infrastructure.learning.models import DatasetRun, DatasetSampleDaily, DatasetSpec
from app.infrastructure.market.models import Instrument
from app.modules.learning.application.seed import seed_dataset_specs
from app.modules.learning.dataset_config import DATASET_BUILD_STEPS, PIT_DAILY_CORE_CODE, PIT_DAILY_CORE_VERSION
from app.modules.market.application.workflows import create_workflow
from app.worker import tasks as worker_tasks

router = APIRouter()


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


class DatasetSpecResponse(BaseModel):
    id: str
    code: str
    version: int
    description: str | None
    feature_manifest: list[dict[str, Any]]
    relation_contexts: list[dict[str, Any]]
    label_spec: dict[str, Any]
    quality_policy: dict[str, Any]
    basic_feature_set_code: str
    basic_feature_set_version: int
    technical_feature_set_code: str
    technical_feature_set_version: int
    technical_model_code: str
    technical_model_version: int
    technical_model_config_hash: str | None
    relation_set_code: str
    relation_set_version: int
    universe_policy: str
    is_active: bool


class DatasetRunResponse(BaseModel):
    id: str
    dataset_spec_id: str
    dataset_spec_code: str | None = None
    dataset_spec_version: int | None = None
    date_from: date | None
    date_to: date | None
    started_at: str | None
    finished_at: str | None
    status: str
    instruments_total: int
    samples_total: int
    eligible_1d: int
    eligible_5d: int
    eligible_10d: int
    eligible_20d: int
    core_invalid: int
    technical_missing: int
    relation_missing: int
    invalid_labels: int
    pit_violations: int
    pit_status: str
    dataset_hash: str | None
    coverage_summary: dict[str, Any] | None = None
    workflow_id: str | None
    error_message: str | None
    duration_sec: float | None = None


class DatasetOverviewResponse(BaseModel):
    active_dataset_spec: str
    last_run: DatasetRunResponse | None
    samples: int = 0
    eligible_1d: int = 0
    eligible_5d: int = 0
    eligible_10d: int = 0
    eligible_20d: int = 0
    relations_coverage: dict[str, Any] | None = None
    pit_status: str | None = None
    dataset_hash: str | None = None


class DatasetSampleResponse(BaseModel):
    id: str
    instrument_id: str
    ticker: str | None = None
    as_of_date: date
    features: dict[str, Any]
    labels: dict[str, Any]
    feature_quality: dict[str, Any]
    label_quality: dict[str, Any]
    training_eligibility: dict[str, Any]
    lineage: dict[str, Any]
    content_hash: str


class BuildRequest(BaseModel):
    date_from: date
    date_to: date | None = None
    dataset_spec_code: str = PIT_DAILY_CORE_CODE
    dataset_spec_version: int = PIT_DAILY_CORE_VERSION
    instrument_ids: list[int] | None = None


class WorkflowStartResponse(BaseModel):
    workflow_id: str
    status: str


def _run_to_response(row: DatasetRun, spec: DatasetSpec | None = None) -> DatasetRunResponse:
    duration = None
    if row.started_at and row.finished_at:
        duration = (row.finished_at - row.started_at).total_seconds()
    return DatasetRunResponse(
        id=str(row.id),
        dataset_spec_id=str(row.dataset_spec_id),
        dataset_spec_code=spec.code if spec else None,
        dataset_spec_version=spec.version if spec else None,
        date_from=row.date_from,
        date_to=row.date_to,
        started_at=_dt(row.started_at),
        finished_at=_dt(row.finished_at),
        status=row.status,
        instruments_total=row.instruments_total,
        samples_total=row.samples_total,
        eligible_1d=row.eligible_1d,
        eligible_5d=row.eligible_5d,
        eligible_10d=row.eligible_10d,
        eligible_20d=row.eligible_20d,
        core_invalid=row.core_invalid,
        technical_missing=row.technical_missing,
        relation_missing=row.relation_missing,
        invalid_labels=row.invalid_labels,
        pit_violations=row.pit_violations,
        pit_status=row.pit_status,
        dataset_hash=row.dataset_hash,
        coverage_summary=row.coverage_summary,
        workflow_id=str(row.workflow_id) if row.workflow_id is not None else None,
        error_message=row.error_message,
        duration_sec=duration,
    )


@router.get("/datasets/overview", response_model=DatasetOverviewResponse)
def datasets_overview() -> DatasetOverviewResponse:
    with core_session() as session:
        seed_dataset_specs(session)
        session.commit()
        active = session.scalar(select(DatasetSpec).where(DatasetSpec.is_active.is_(True)))
        last = session.scalar(
            select(DatasetRun)
            .where(DatasetRun.status.in_(["SUCCESS", "WARNING"]))
            .order_by(desc(DatasetRun.finished_at))
            .limit(1)
        )
        spec = session.get(DatasetSpec, last.dataset_spec_id) if last else active
        return DatasetOverviewResponse(
            active_dataset_spec=f"{active.code} v{active.version}" if active else "—",
            last_run=_run_to_response(last, spec) if last else None,
            samples=last.samples_total if last else 0,
            eligible_1d=last.eligible_1d if last else 0,
            eligible_5d=last.eligible_5d if last else 0,
            eligible_10d=last.eligible_10d if last else 0,
            eligible_20d=last.eligible_20d if last else 0,
            relations_coverage=(last.coverage_summary or {}).get("relations") if last else None,
            pit_status=last.pit_status if last else None,
            dataset_hash=last.dataset_hash if last else None,
        )


@router.get("/datasets/specs", response_model=list[DatasetSpecResponse])
def list_specs() -> list[DatasetSpecResponse]:
    with core_session() as session:
        seed_dataset_specs(session)
        session.commit()
        rows = list(session.scalars(select(DatasetSpec).order_by(DatasetSpec.code, DatasetSpec.version)))
        return [
            DatasetSpecResponse(
                id=str(r.id),
                code=r.code,
                version=r.version,
                description=r.description,
                feature_manifest=list(r.feature_manifest or []),
                relation_contexts=list(r.relation_contexts or []),
                label_spec=dict(r.label_spec or {}),
                quality_policy=dict(r.quality_policy or {}),
                basic_feature_set_code=r.basic_feature_set_code,
                basic_feature_set_version=r.basic_feature_set_version,
                technical_feature_set_code=r.technical_feature_set_code,
                technical_feature_set_version=r.technical_feature_set_version,
                technical_model_code=r.technical_model_code,
                technical_model_version=r.technical_model_version,
                technical_model_config_hash=r.technical_model_config_hash,
                relation_set_code=r.relation_set_code,
                relation_set_version=r.relation_set_version,
                universe_policy=r.universe_policy,
                is_active=r.is_active,
            )
            for r in rows
        ]


@router.get("/datasets/runs", response_model=list[DatasetRunResponse])
def list_runs(limit: int = Query(default=50, ge=1, le=200)) -> list[DatasetRunResponse]:
    with core_session() as session:
        rows = list(session.scalars(select(DatasetRun).order_by(desc(DatasetRun.id)).limit(limit)))
        out = []
        for r in rows:
            spec = session.get(DatasetSpec, r.dataset_spec_id)
            out.append(_run_to_response(r, spec))
        return out


@router.get("/datasets/runs/{run_id}", response_model=DatasetRunResponse)
def get_run(run_id: int) -> DatasetRunResponse:
    with core_session() as session:
        row = session.get(DatasetRun, run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Dataset run not found")
        return _run_to_response(row, session.get(DatasetSpec, row.dataset_spec_id))


@router.get("/datasets/runs/{run_id}/manifest")
def get_manifest(run_id: int) -> dict[str, Any]:
    with core_session() as session:
        row = session.get(DatasetRun, run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Dataset run not found")
        payload = dict(row.manifest or {})
        # Acceptance / diagnostics: expose coverage beside frozen semantic contract fields.
        if row.coverage_summary is not None:
            payload.setdefault("coverage_summary", row.coverage_summary)
        return payload


@router.get("/datasets/runs/{run_id}/summary")
def get_run_summary(run_id: int) -> dict[str, Any]:
    with core_session() as session:
        row = session.get(DatasetRun, run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Dataset run not found")
        spec = session.get(DatasetSpec, row.dataset_spec_id)
        payload = _run_to_response(row, spec)
        return {
            **payload.model_dump(),
            "coverage": row.coverage_summary or {},
            "manifest": {
                "dataset_hash": (row.manifest or {}).get("dataset_hash"),
                "values_hash": (row.manifest or {}).get("values_hash"),
                "hash_policy": (row.manifest or {}).get("hash_policy"),
                "source_versions": (row.manifest or {}).get("source_versions"),
                "sample_counts": (row.manifest or {}).get("sample_counts"),
            },
        }


@router.get("/datasets/runs/{run_id}/samples", response_model=list[DatasetSampleResponse])
def list_samples(
    run_id: int,
    instrument: str | None = None,
    date_filter: Annotated[date | None, Query(alias="date")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    eligible_horizon: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[DatasetSampleResponse]:
    with core_session() as session:
        run = session.get(DatasetRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Dataset run not found")
        q = (
            select(DatasetSampleDaily, Instrument.symbol)
            .join(Instrument, Instrument.id == DatasetSampleDaily.instrument_id)
            .where(DatasetSampleDaily.dataset_run_id == run_id)
        )
        if instrument:
            q = q.where(Instrument.symbol.ilike(f"%{instrument}%"))
        if date_filter is not None:
            q = q.where(DatasetSampleDaily.as_of_date == date_filter)
        if date_from is not None:
            q = q.where(DatasetSampleDaily.as_of_date >= date_from)
        if date_to is not None:
            q = q.where(DatasetSampleDaily.as_of_date <= date_to)
        q = q.order_by(DatasetSampleDaily.as_of_date.desc(), Instrument.symbol).offset(offset).limit(limit)
        out: list[DatasetSampleResponse] = []
        for sample, ticker in session.execute(q).all():
            if eligible_horizon is not None:
                key = f"training_eligible_{eligible_horizon}d"
                if not (sample.training_eligibility or {}).get(key):
                    continue
            out.append(
                DatasetSampleResponse(
                    id=str(sample.id),
                    instrument_id=str(sample.instrument_id),
                    ticker=ticker,
                    as_of_date=sample.as_of_date,
                    features=sample.features or {},
                    labels=sample.labels or {},
                    feature_quality=sample.feature_quality or {},
                    label_quality=sample.label_quality or {},
                    training_eligibility=sample.training_eligibility or {},
                    lineage=sample.lineage or {},
                    content_hash=sample.content_hash,
                )
            )
        return out


@router.get("/datasets/runs/{run_id}/samples/{sample_id}", response_model=DatasetSampleResponse)
def get_sample(run_id: int, sample_id: int) -> DatasetSampleResponse:
    with core_session() as session:
        sample = session.get(DatasetSampleDaily, sample_id)
        if sample is None or sample.dataset_run_id != run_id:
            raise HTTPException(status_code=404, detail="Sample not found")
        inst = session.get(Instrument, sample.instrument_id)
        return DatasetSampleResponse(
            id=str(sample.id),
            instrument_id=str(sample.instrument_id),
            ticker=inst.symbol if inst else None,
            as_of_date=sample.as_of_date,
            features=sample.features or {},
            labels=sample.labels or {},
            feature_quality=sample.feature_quality or {},
            label_quality=sample.label_quality or {},
            training_eligibility=sample.training_eligibility or {},
            lineage=sample.lineage or {},
            content_hash=sample.content_hash,
        )


@router.post("/datasets/build", response_model=WorkflowStartResponse)
def start_build(body: BuildRequest) -> WorkflowStartResponse:
    if body.date_to is not None and body.date_to < body.date_from:
        raise HTTPException(status_code=400, detail="date_to must be >= date_from")
    with core_session() as session:
        seed_dataset_specs(session)
        spec = session.scalar(
            select(DatasetSpec).where(
                DatasetSpec.code == body.dataset_spec_code,
                DatasetSpec.version == body.dataset_spec_version,
            )
        )
        if spec is None:
            raise HTTPException(status_code=404, detail="Unknown dataset spec")
        workflow = create_workflow(
            session,
            "DatasetBuild",
            (
                f"Dataset build {body.dataset_spec_code} v{body.dataset_spec_version} "
                f"{body.date_from}→{body.date_to or 'latest'}"
            ),
            DATASET_BUILD_STEPS,
        )
        session.commit()
        worker_tasks.dataset_build.delay(
            workflow.id,
            body.date_from.isoformat(),
            body.date_to.isoformat() if body.date_to else None,
            body.dataset_spec_code,
            body.dataset_spec_version,
            body.instrument_ids,
        )
        return WorkflowStartResponse(workflow_id=str(workflow.id), status="RUNNING")
