"""Runtime configuration from environment variables."""

from functools import lru_cache

from pydantic import Field
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

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

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
