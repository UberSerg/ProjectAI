"""Test fixtures and shared env defaults."""

from __future__ import annotations

import os

import pytest

# Ensure settings are available during module import (before fixtures run).
_DEFAULTS = {
    "APP_ENV": "test",
    "APP_NAME": "ProjectAI",
    "CORE_DATABASE_HOST": "localhost",
    "CORE_DATABASE_PORT": "5432",
    "CORE_DATABASE_NAME": "projectai_core",
    "CORE_DATABASE_USER": "projectai",
    "CORE_DATABASE_PASSWORD": "projectai_core_dev",
    "MEMORY_DATABASE_HOST": "localhost",
    "MEMORY_DATABASE_PORT": "5433",
    "MEMORY_DATABASE_NAME": "projectai_memory",
    "MEMORY_DATABASE_USER": "projectai",
    "MEMORY_DATABASE_PASSWORD": "projectai_memory_dev",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "REDIS_DB": "0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/1",
}

for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)

from app.core.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
