"""System endpoints: health, info, technology events, diagnostics."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.application.system.diagnostics import build_diagnostics_payload, build_diagnostics_text
from app.application.system.event_log import (
    cleanup_old_days,
    event_to_dict,
    get_event,
    list_events,
    new_trace_id,
    write_event,
)
from app.application.system.health import get_liveness, get_readiness, get_system_health
from app.application.system.info import get_system_info
from app.application.system.sanitize import sanitize_text
from app.core.config import get_settings
from app.infrastructure.db.session import core_session

router = APIRouter()


class LivenessResponse(BaseModel):
    status: str


class HealthResponse(BaseModel):
    status: str
    services: dict[str, str] = Field(default_factory=dict)


class InfoResponse(BaseModel):
    name: str
    version: str
    environment: str
    api_version: str
    market_update_enabled: bool = False
    raw_storage_path: str = ""


class ClientEventRequest(BaseModel):
    level: Literal["INFO", "WARNING", "ERROR"] = "ERROR"
    component: str = Field(default="frontend", max_length=120)
    event_type: str = Field(default="frontend_runtime_error", max_length=120)
    message: str = Field(..., max_length=4000)
    route: str | None = Field(default=None, max_length=500)
    stack: str | None = Field(default=None, max_length=8000)
    details: dict[str, Any] | None = None
    trace_id: str | None = Field(default=None, max_length=64)


@router.get("/health/live", response_model=LivenessResponse)
def health_live() -> LivenessResponse:
    return LivenessResponse(status=get_liveness().status)


@router.get("/health/ready", response_model=HealthResponse)
def health_ready() -> HealthResponse:
    result = get_readiness()
    return HealthResponse(status=result.status, services=dict(result.services))


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    result = get_system_health()
    return HealthResponse(status=result.status, services=dict(result.services))


@router.get("/info", response_model=InfoResponse)
def info() -> InfoResponse:
    result = get_system_info()
    return InfoResponse(
        name=result.name,
        version=result.version,
        environment=result.environment,
        api_version=result.api_version,
        market_update_enabled=result.market_update_enabled,
        raw_storage_path=result.raw_storage_path,
    )


@router.get("/events")
def get_events(
    level: str | None = None,
    component: str | None = None,
    workflow_id: int | None = None,
    trace_id: str | None = None,
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    with core_session() as session:
        rows = list_events(
            session,
            level=level,
            component=component,
            workflow_id=workflow_id,
            trace_id=trace_id,
            limit=limit,
        )
        return {"items": [event_to_dict(row) for row in rows], "total": len(rows)}


@router.get("/events/{event_id}")
def get_event_detail(event_id: int) -> dict[str, Any]:
    with core_session() as session:
        row = get_event(session, event_id)
        if row is None:
            raise HTTPException(404, "Event not found")
        return event_to_dict(row)


@router.post("/events/client")
def post_client_event(payload: ClientEventRequest, request: Request) -> dict[str, Any]:
    settings = get_settings()
    stack = sanitize_text(
        payload.stack or "",
        max_len=settings.tech_log_client_max_stack_chars,
    )
    details = {
        **(payload.details or {}),
        "route": payload.route,
        "stack": stack or None,
        "user_agent": request.headers.get("user-agent", "")[:200],
    }
    try:
        with core_session() as session:
            cleanup_old_days(session)
            row = write_event(
                session,
                level=payload.level,
                component=payload.component or "frontend",
                event_type=payload.event_type or "frontend_runtime_error",
                message=payload.message[:2000],
                details={k: v for k, v in details.items() if v is not None},
                trace_id=payload.trace_id or new_trace_id(),
                enforce_limits=True,
            )
            return {"accepted": True, "id": str(row.id) if row else None}
    except Exception:  # noqa: BLE001 — never recurse client error reporting
        return {"accepted": False}


@router.get("/diagnostics")
def diagnostics_json() -> dict[str, Any]:
    with core_session() as session:
        return build_diagnostics_payload(session)


@router.get("/diagnostics/text")
def diagnostics_text() -> Response:
    with core_session() as session:
        body = build_diagnostics_text(session)
    # Explicit UTF-8 bytes + charset (Windows clients must not guess the encoding).
    return Response(content=body.encode("utf-8"), media_type="text/plain; charset=utf-8")
