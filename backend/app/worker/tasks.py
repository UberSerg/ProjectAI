"""Celery tasks — technical foundation + Market Data V1."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.core.logging import get_logger
from app.infrastructure.db.session import core_session
from app.infrastructure.market.models import Workflow
from app.modules.market.application.data_quality import DataQualityContext, run_data_quality_checks
from app.modules.market.application.ingest import MarketIngestionService
from app.modules.market.application.workflows import finish_workflow, get_step, update_step
from app.worker.celery_app import celery_app

logger = get_logger(__name__, component="worker")


@celery_app.task(name="projectai.ping")
def ping() -> dict[str, str]:
    logger.info("ping_task_executed")
    return {"status": "pong", "timestamp": datetime.now(UTC).isoformat()}


@celery_app.task(name="projectai.market_data_backfill")
def market_data_backfill(
    workflow_id: int,
    symbols: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    with core_session() as session:
        service = MarketIngestionService(session)
        return service.run_backfill(
            symbols=symbols,
            date_from=date.fromisoformat(date_from) if date_from else None,
            date_to=date.fromisoformat(date_to) if date_to else None,
            workflow_id=workflow_id,
        )


@celery_app.task(name="projectai.market_data_update")
def market_data_update(workflow_id: int) -> dict:
    with core_session() as session:
        service = MarketIngestionService(session)
        return service.run_update(workflow_id=workflow_id)


@celery_app.task(name="projectai.market_data_quality_run")
def market_data_quality_run(
    workflow_id: int,
    mode: str = "operational",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    with core_session() as session:
        workflow = session.get(Workflow, workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow {workflow_id} not found")
        update_step(session, get_step(workflow, "Run Data Quality"), "RUNNING")
        context = DataQualityContext(
            mode="historical" if mode == "historical" else "operational",
            date_from=date.fromisoformat(date_from) if date_from else None,
            date_to=date.fromisoformat(date_to) if date_to else None,
        )
        result = run_data_quality_checks(session, context)
        status = "WARNING" if result.get("errors") or result.get("warnings") else "SUCCESS"
        update_step(session, get_step(workflow, "Run Data Quality"), status)
        update_step(session, get_step(workflow, "Finish"), "SUCCESS")
        finish_workflow(session, workflow, status)
        session.commit()
        return {"workflow_id": workflow_id, "result": result}


@celery_app.task(name="projectai.feature_backfill")
def feature_backfill(
    workflow_id: int,
    date_from: str,
    date_to: str | None = None,
    feature_set_code: str = "basic_daily",
    feature_set_version: int = 1,
) -> dict:
    from app.modules.analytics.application.compute import FeatureComputeService

    with core_session() as session:
        service = FeatureComputeService(session)
        return service.run_backfill(
            date_from=date.fromisoformat(date_from),
            date_to=date.fromisoformat(date_to) if date_to else None,
            feature_set_code=feature_set_code,
            feature_set_version=feature_set_version,
            workflow_id=workflow_id,
        )


@celery_app.task(name="projectai.feature_update")
def feature_update(
    workflow_id: int,
    feature_set_code: str = "basic_daily",
    feature_set_version: int = 1,
) -> dict:
    from app.modules.analytics.application.compute import FeatureComputeService

    with core_session() as session:
        service = FeatureComputeService(session)
        return service.run_update(
            feature_set_code=feature_set_code,
            feature_set_version=feature_set_version,
            workflow_id=workflow_id,
        )


@celery_app.task(name="projectai.relations_compute_latest")
def relations_compute_latest(
    workflow_id: int,
    relation_set_code: str = "basic_relations",
    relation_set_version: int = 1,
) -> dict:
    from app.modules.relations.application.compute import RelationsComputeService

    with core_session() as session:
        service = RelationsComputeService(session)
        return service.run_latest(
            relation_set_code=relation_set_code,
            relation_set_version=relation_set_version,
            workflow_id=workflow_id,
        )


@celery_app.task(name="projectai.relations_backfill")
def relations_backfill(
    workflow_id: int,
    as_of_from: str,
    as_of_to: str | None = None,
    cadence: str = "WEEKLY",
    relation_set_code: str = "basic_relations",
    relation_set_version: int = 1,
) -> dict:
    from app.modules.relations.application.compute import RelationsComputeService

    with core_session() as session:
        service = RelationsComputeService(session)
        return service.run_backfill(
            as_of_from=date.fromisoformat(as_of_from),
            as_of_to=date.fromisoformat(as_of_to) if as_of_to else None,
            cadence=cadence,
            relation_set_code=relation_set_code,
            relation_set_version=relation_set_version,
            workflow_id=workflow_id,
        )


@celery_app.task(name="projectai.technical_backfill")
def technical_backfill(
    workflow_id: int,
    date_from: str,
    date_to: str | None = None,
    instrument_ids: list[int] | None = None,
    model_code: str = "rules",
    model_version: int = 1,
) -> dict:
    from app.modules.technical.application.compute import TechnicalComputeService

    with core_session() as session:
        service = TechnicalComputeService(session)
        return service.run_backfill(
            date_from=date.fromisoformat(date_from),
            date_to=date.fromisoformat(date_to) if date_to else None,
            instrument_ids=instrument_ids,
            model_code=model_code,
            model_version=model_version,
            workflow_id=workflow_id,
        )


@celery_app.task(name="projectai.technical_update")
def technical_update(
    workflow_id: int,
    model_code: str = "rules",
    model_version: int = 1,
) -> dict:
    from app.modules.technical.application.compute import TechnicalComputeService

    with core_session() as session:
        service = TechnicalComputeService(session)
        return service.run_update(
            model_code=model_code,
            model_version=model_version,
            workflow_id=workflow_id,
        )


@celery_app.task(name="projectai.dataset_build")
def dataset_build(
    workflow_id: int,
    date_from: str,
    date_to: str | None = None,
    dataset_spec_code: str = "pit_daily_core",
    dataset_spec_version: int = 1,
    instrument_ids: list[int] | None = None,
) -> dict:
    from app.modules.learning.application.builder import PITDatasetBuilder

    with core_session() as session:
        service = PITDatasetBuilder(session)
        return service.run_build(
            date_from=date.fromisoformat(date_from),
            date_to=date.fromisoformat(date_to) if date_to else None,
            dataset_spec_code=dataset_spec_code,
            dataset_spec_version=dataset_spec_version,
            instrument_ids=instrument_ids,
            workflow_id=workflow_id,
        )


@celery_app.task(name="projectai.cleanup_technology_log")
def cleanup_technology_log() -> dict:
    """Keep system.event_logs bounded to the current UTC day and size limit."""
    from app.application.system.event_log import cleanup_old_days, enforce_day_limit

    with core_session() as session:
        deleted_old = cleanup_old_days(session)
        trimmed = enforce_day_limit(session)
        session.commit()
    return {"deleted_old": deleted_old, "trimmed": trimmed}


@celery_app.task(name="projectai.market_data_update_scheduled")
def market_data_update_scheduled() -> dict:
    with core_session() as session:
        from app.modules.market.application.ingest import BACKFILL_STEPS
        from app.modules.market.application.workflows import create_workflow

        workflow = create_workflow(
            session,
            "MarketDataUpdate",
            "Scheduled market data update",
            BACKFILL_STEPS,
        )
        session.commit()
        workflow_id = workflow.id
    return market_data_update(workflow_id)
