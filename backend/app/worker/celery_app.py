"""Celery application shared by worker and beat scheduler."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings


def _parse_cron(expr: str) -> dict[str, object]:
    minute, hour, day_of_month, month_of_year, day_of_week = expr.split()
    return {
        "minute": minute,
        "hour": hour,
        "day_of_month": day_of_month,
        "month_of_year": month_of_year,
        "day_of_week": day_of_week,
    }


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "projectai",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.worker.tasks"],
    )
    beat_schedule = {
        "technology-log-cleanup-nightly": {
            "task": "projectai.cleanup_technology_log",
            "schedule": crontab(minute=5, hour=0),
        },
    }
    if settings.market_update_enabled:
        beat_schedule["market-data-daily-update"] = {
            "task": "projectai.market_data_update_scheduled",
            "schedule": crontab(**_parse_cron(settings.market_update_cron)),
        }
    if settings.daily_research_cycle_enabled:
        beat_schedule["daily-research-cycle"] = {
            "task": "projectai.daily_research_cycle_scheduled",
            "schedule": crontab(
                minute=settings.daily_research_cycle_minute,
                hour=settings.daily_research_cycle_hour,
            ),
        }
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        beat_schedule=beat_schedule,
    )
    return app


celery_app = create_celery_app()
