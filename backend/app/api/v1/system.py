"""System endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.application.system.health import get_liveness, get_readiness, get_system_health
from app.application.system.info import get_system_info

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


@router.get("/health/live", response_model=LivenessResponse)
def health_live() -> LivenessResponse:
    result = get_liveness()
    return LivenessResponse(status=result.status)


@router.get("/health/ready", response_model=HealthResponse)
def health_ready() -> HealthResponse:
    result = get_readiness()
    return HealthResponse(status=result.status, services=result.services)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    result = get_system_health()
    return HealthResponse(status=result.status, services=result.services)


@router.get("/info", response_model=InfoResponse)
def info() -> InfoResponse:
    result = get_system_info()
    return InfoResponse(
        name=result.name,
        version=result.version,
        environment=result.environment,
        api_version=result.api_version,
    )
