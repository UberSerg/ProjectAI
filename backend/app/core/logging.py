"""Structured logging foundation."""

from __future__ import annotations

import logging
import sys
from typing import Any

from pythonjsonlogger.json import JsonFormatter

from app.core.config import get_settings


class ComponentFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "component"):
            record.component = "app"
        return True


def configure_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ComponentFilter())

    if settings.log_format == "json":
        formatter = JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(component)s %(message)s",
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
                "name": "logger",
            },
        )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(component)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)


def get_logger(name: str, component: str | None = None) -> logging.LoggerAdapter[Any]:
    logger = logging.getLogger(name)
    default_component = name.split(".")[1] if "." in name else name
    return logging.LoggerAdapter(logger, {"component": component or default_component})
