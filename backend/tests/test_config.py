"""Configuration tests."""

from app.core.config import get_settings


def test_settings_load_from_env() -> None:
    settings = get_settings()
    assert settings.app_name == "ProjectAI"
    assert settings.core_database_url.startswith("postgresql+psycopg://")
    assert settings.memory_database_url.startswith("postgresql+psycopg://")
    assert "redis://" in settings.redis_url
    assert settings.polza_base_url
