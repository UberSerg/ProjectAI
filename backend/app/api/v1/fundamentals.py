"""Read-only API for the Fundamental & Event Intelligence V1 data foundation.

Payloads are honest: with no accepted report/dividend provider these endpoints return
NOT_READY with the blocking reason instead of a plausible-looking empty structure.
Nothing here participates in the daily operational cycle.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.infrastructure.db.session import core_session
from app.modules.fundamentals.application import read_models
from app.modules.fundamentals.application.features_event import materialize_event_daily
from app.modules.fundamentals.application.features_fundamental import (
    materialize_fundamental_daily,
)
from app.modules.fundamentals.application.quality import run_quality_checks

router = APIRouter()


@router.get("/status")
def fundamentals_status() -> dict[str, Any]:
    with core_session() as session:
        return read_models.status_payload(session)


@router.get("/sources/audit")
def fundamentals_source_audit() -> dict[str, Any]:
    with core_session() as session:
        return read_models.source_audit_payload(session)


@router.get("/coverage")
def fundamentals_coverage() -> dict[str, Any]:
    with core_session() as session:
        return read_models.coverage_payload(session)


@router.get("/readiness")
def fundamentals_readiness() -> dict[str, Any]:
    with core_session() as session:
        return read_models.readiness_payload(session)


@router.get("/quality")
def fundamentals_quality() -> dict[str, Any]:
    with core_session() as session:
        return run_quality_checks(session)


@router.get("/metrics")
def fundamentals_metrics() -> dict[str, Any]:
    with core_session() as session:
        return read_models.metrics_payload(session)


@router.get("/issuers")
def fundamentals_issuers(
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    with core_session() as session:
        return read_models.issuers_payload(session, limit=limit, offset=offset)


@router.get("/mappings")
def fundamentals_mappings(
    mapping_status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    with core_session() as session:
        return read_models.mappings_payload(session, mapping_status=mapping_status, limit=limit)


@router.get("/issuers/{issuer_id}/reports")
def fundamentals_reports(
    issuer_id: int,
    as_of: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    with core_session() as session:
        return read_models.reports_payload(session, issuer_id=issuer_id, as_of=as_of)


@router.get("/dividends")
def fundamentals_dividends(
    instrument_id: Annotated[int | None, Query()] = None,
    issuer_id: Annotated[int | None, Query()] = None,
    as_of: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    with core_session() as session:
        return read_models.dividends_payload(
            session, as_of=as_of, instrument_id=instrument_id, issuer_id=issuer_id
        )


@router.get("/events")
def fundamentals_events(
    instrument_id: Annotated[int | None, Query()] = None,
    as_of: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    with core_session() as session:
        return read_models.events_payload(
            session, as_of=as_of, instrument_id=instrument_id, limit=limit
        )


@router.get("/features/fundamental-daily")
def fundamentals_feature_preview(
    as_of: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Preview of the `fundamental_daily` contract. Computed on demand, never stored."""
    with core_session() as session:
        result = materialize_fundamental_daily(session, as_of or date.today())
        payload = result.to_dict()
        payload["rows"] = payload["rows"][:limit]
        return payload


@router.get("/features/event-daily")
def fundamentals_event_feature_preview(
    as_of: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Preview of the `event_daily` contract. Computed on demand, never stored."""
    with core_session() as session:
        result = materialize_event_daily(session, as_of or date.today())
        payload = result.to_dict()
        payload["rows"] = payload["rows"][:limit]
        return payload
