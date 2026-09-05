"""Runtime configuration from environment variables."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="ProjectAI", alias="APP_NAME")
    app_port: int = Field(default=8000, alias="APP_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")

    core_database_host: str = Field(alias="CORE_DATABASE_HOST")
    core_database_port: int = Field(default=5432, alias="CORE_DATABASE_PORT")
    core_database_name: str = Field(alias="CORE_DATABASE_NAME")
    core_database_user: str = Field(alias="CORE_DATABASE_USER")
    core_database_password: str = Field(alias="CORE_DATABASE_PASSWORD")

    memory_database_host: str = Field(alias="MEMORY_DATABASE_HOST")
    memory_database_port: int = Field(default=5432, alias="MEMORY_DATABASE_PORT")
    memory_database_name: str = Field(alias="MEMORY_DATABASE_NAME")
    memory_database_user: str = Field(alias="MEMORY_DATABASE_USER")
    memory_database_password: str = Field(alias="MEMORY_DATABASE_PASSWORD")

    redis_host: str = Field(alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")

    celery_broker_url: str = Field(alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(alias="CELERY_RESULT_BACKEND")

    polza_api_key: str = Field(default="", alias="POLZA_API_KEY")
    polza_base_url: str = Field(default="https://api.polza.ai/v1", alias="POLZA_BASE_URL")
    polza_default_model: str = Field(default="", alias="POLZA_DEFAULT_MODEL")

    raw_data_path: str = Field(default="/data/raw", alias="RAW_DATA_PATH")
    models_data_path: str = Field(default="/data/models", alias="MODELS_DATA_PATH")
    market_update_enabled: bool = Field(default=False, alias="MARKET_UPDATE_ENABLED")
    market_update_cron: str = Field(default="0 18 * * 1-5", alias="MARKET_UPDATE_CRON")
    # Fundamentals V1 is storage + identity only; no beat schedule is registered.
    fundamentals_update_enabled: bool = Field(default=False, alias="FUNDAMENTALS_UPDATE_ENABLED")
    edisclosure_gateway_enabled: bool = Field(default=False, alias="EDISCLOSURE_GATEWAY_ENABLED")
    edisclosure_gateway_base_url: str = Field(
        default="https://gateway.e-disclosure.ru", alias="EDISCLOSURE_GATEWAY_BASE_URL"
    )
    edisclosure_gateway_username: str = Field(default="", alias="EDISCLOSURE_GATEWAY_USERNAME")
    edisclosure_gateway_secret: str = Field(default="", alias="EDISCLOSURE_GATEWAY_SECRET")
    gir_bo_enabled: bool = Field(default=False, alias="GIR_BO_ENABLED")
    gir_bo_base_url: str = Field(default="https://bo.nalog.gov.ru", alias="GIR_BO_BASE_URL")
    gir_bo_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        alias="GIR_BO_USER_AGENT",
    )
    daily_research_cycle_enabled: bool = Field(default=False, alias="DAILY_RESEARCH_CYCLE_ENABLED")
    daily_research_cycle_hour: int = Field(default=18, alias="DAILY_RESEARCH_CYCLE_HOUR")
    daily_research_cycle_minute: int = Field(default=30, alias="DAILY_RESEARCH_CYCLE_MINUTE")
    daily_research_cycle_timezone: str = Field(default="UTC", alias="DAILY_RESEARCH_CYCLE_TIMEZONE")
    moex_base_url: str = Field(default="https://iss.moex.com", alias="MOEX_BASE_URL")
    cbr_base_url: str = Field(default="https://www.cbr.ru", alias="CBR_BASE_URL")
    http_timeout_seconds: float = Field(default=30.0, alias="HTTP_TIMEOUT_SECONDS")
    http_max_retries: int = Field(default=3, alias="HTTP_MAX_RETRIES")
    http_retry_backoff_seconds: float = Field(default=1.0, alias="HTTP_RETRY_BACKOFF_SECONDS")
    market_default_backfill_from: date = Field(
        default=date(2015, 1, 1), alias="MARKET_DEFAULT_BACKFILL_FROM"
    )

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    tech_log_max_events_per_day: int = Field(default=20_000, alias="TECH_LOG_MAX_EVENTS_PER_DAY")
    tech_log_client_max_stack_chars: int = Field(default=4000, alias="TECH_LOG_CLIENT_MAX_STACK_CHARS")

    @field_validator("market_default_backfill_from", mode="before")
    @classmethod
    def _parse_backfill_from(cls, value: object) -> object:
        if isinstance(value, str):
            return date.fromisoformat(value)
        return value

    @property
    def core_database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.core_database_user}:{self.core_database_password}"
            f"@{self.core_database_host}:{self.core_database_port}/{self.core_database_name}"
        )

    @property
    def memory_database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.memory_database_user}:{self.memory_database_password}"
            f"@{self.memory_database_host}:{self.memory_database_port}/{self.memory_database_name}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
