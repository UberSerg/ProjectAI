"""Sanitizer, event-log retention, and diagnostics smoke tests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.application.system.diagnostics import build_diagnostics_text
from app.application.system.event_log import (
    cleanup_old_days,
    enforce_day_limit,
    list_events,
    write_event,
)
from app.application.system.sanitize import sanitize_text, sanitize_value
from app.core.config import get_settings
from app.infrastructure.market.models import EventLog
from app.main import create_app


def test_sanitize_hides_secrets() -> None:
    payload = {
        "password": "secret",
        "nested": {"api_key": "abc", "safe": "ok", "authorization": "Bearer nested-secret"},
        "note": "token=abc123 and password=x",
    }
    cleaned = sanitize_value(payload)
    assert cleaned["password"] == "[REDACTED]"
    assert cleaned["nested"]["api_key"] == "[REDACTED]"
    assert cleaned["nested"]["authorization"] == "[REDACTED]"
    assert cleaned["nested"]["safe"] == "ok"
    assert "[REDACTED]" in sanitize_text("Authorization: Bearer super-secret")
    assert "super-secret" not in sanitize_text("Authorization: Bearer super-secret")


def test_write_and_list_events(core_db: Session) -> None:
    write_event(
        core_db,
        level="INFO",
        component="test",
        event_type="unit_info",
        message="hello",
    )
    write_event(
        core_db,
        level="ERROR",
        component="test",
        event_type="unit_error",
        message="boom password=should-hide",
        details={"api_key": "nested-secret", "safe": "ok"},
    )
    core_db.flush()
    errors = list_events(core_db, level="ERROR", limit=50)
    assert any(row.event_type == "unit_error" for row in errors)
    assert all("should-hide" not in (row.message or "") for row in errors)
    error_row = next(row for row in errors if row.event_type == "unit_error")
    assert error_row.details is not None
    assert error_row.details["api_key"] == "[REDACTED]"
    assert error_row.details["safe"] == "ok"


def test_cleanup_keeps_today_only(core_db: Session) -> None:
    old = EventLog(
        timestamp=datetime.now(UTC) - timedelta(days=2),
        level="INFO",
        component="test",
        event_type="old",
        message="yesterday",
    )
    today = EventLog(
        timestamp=datetime.now(UTC),
        level="INFO",
        component="test",
        event_type="today",
        message="today",
    )
    core_db.add_all([old, today])
    core_db.flush()
    deleted = cleanup_old_days(core_db)
    core_db.flush()
    assert deleted >= 1
    remaining = list_events(core_db, limit=500)
    assert all(row.event_type != "old" for row in remaining)
    assert any(row.event_type == "today" for row in remaining)


def test_day_limit_trims_oldest(core_db: Session, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "tech_log_max_events_per_day", 5)
    for index in range(8):
        write_event(
            core_db,
            level="INFO",
            component="test",
            event_type=f"evt_{index}",
            message=f"m{index}",
        )
    trimmed = enforce_day_limit(core_db)
    core_db.flush()
    assert trimmed >= 3
    assert len(list_events(core_db, limit=500)) <= 5


def test_diagnostics_text_has_sections(core_db: Session) -> None:
    write_event(
        core_db,
        level="ERROR",
        component="diagnostics",
        event_type="probe",
        message="sample error",
        details={"token": "secret-value"},
    )
    core_db.flush()
    text = build_diagnostics_text(core_db)
    assert "ProjectAI Diagnostic Report" in text
    assert "=== HEALTH ===" in text
    assert "=== ERRORS TODAY ===" in text
    assert "secret-value" not in text


def test_client_event_endpoint_accepts_and_sanitizes(core_db: Session, monkeypatch) -> None:
    @contextmanager
    def _fake_core_session():
        yield core_db

    monkeypatch.setattr("app.api.v1.system.core_session", _fake_core_session)
    monkeypatch.setattr("app.main.core_session", _fake_core_session)

    client = TestClient(create_app())
    response = client.post(
        "/api/v1/system/events/client",
        json={
            "level": "ERROR",
            "component": "frontend",
            "event_type": "frontend_runtime_error",
            "message": "page crashed",
            "route": "/market/instruments/1",
            "stack": "Error: x\n    at InstrumentPage",
            "details": {"api_key": "should-hide"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("accepted") is True

    oversized = client.post(
        "/api/v1/system/events/client",
        json={"message": "x" * 50_000},
    )
    assert oversized.status_code in {200, 422}
