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
