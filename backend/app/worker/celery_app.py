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
    if getattr(settings, "eod_readiness_retry_enabled", False):
        # Lightweight readiness check only — does not re-run the full cycle every poll.
        minutes = max(1, int(getattr(settings, "eod_readiness_retry_minutes", 15) or 15))
        beat_schedule["eod-readiness-retry"] = {
            "task": "projectai.eod_readiness_retry",
            "schedule": crontab(minute=f"*/{minutes}"),
        }
    if settings.intraday_market_enabled:
        # Every N minutes during the UTC day; task no-ops cheaply if disabled at runtime.
        beat_schedule["intraday-market-refresh"] = {
            "task": "projectai.refresh_intraday_market",
            "schedule": crontab(
                minute=f"*/{max(1, int(settings.intraday_refresh_minutes))}",
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
