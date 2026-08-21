"""System endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.application.system.health import get_system_health
from app.application.system.info import get_system_info

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    services: dict[str, str] = Field(default_factory=dict)


class InfoResponse(BaseModel):
    name: str
    version: str
    environment: str
    api_version: str


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
