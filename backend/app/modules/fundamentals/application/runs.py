"""fundamentals.ingestion_runs bookkeeping shared by every ingest / sync service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.fundamentals.domain.types import IngestionStatus
from app.modules.fundamentals.infrastructure.models import IngestionRun


def start_run(
    session: Session, provider: str, *, requested_range: str | None = None
) -> IngestionRun:
    run = IngestionRun(
        provider=provider,
        requested_range=requested_range,
        status=IngestionStatus.RUNNING.value,
        summary={},
    )
    session.add(run)
    session.flush()
    return run


def finish_run(
    session: Session,
    run: IngestionRun,
    *,
    status: IngestionStatus,
    summary: dict[str, Any] | None = None,
) -> IngestionRun:
    run.status = status.value
    run.finished_at = datetime.now(UTC)
    if summary is not None:
        run.summary = summary
    session.add(run)
    session.flush()
    return run
