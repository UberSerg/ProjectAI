"""System info use-case."""

from __future__ import annotations

from dataclasses import dataclass

from app import __version__
from app.core.config import get_settings


@dataclass(slots=True)
class SystemInfo:
    name: str
    version: str
    environment: str
    api_version: str


def get_system_info() -> SystemInfo:
    settings = get_settings()
    return SystemInfo(
        name=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        api_version="v1",
    )
