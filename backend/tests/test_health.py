"""Health endpoint tests with mocked infrastructure."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_structure(monkeypatch) -> None:
    monkeypatch.setattr("app.application.system.health.check_core_database", lambda: True)
    monkeypatch.setattr("app.application.system.health.check_memory_database", lambda: True)
    monkeypatch.setattr("app.application.system.health.check_redis", lambda: True)
    monkeypatch.setattr("app.application.system.health.check_worker", lambda: True)

    client = TestClient(create_app())
    response = client.get("/api/v1/system/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["services"]["core_database"] == "ok"
    assert payload["services"]["memory_database"] == "ok"
    assert payload["services"]["redis"] == "ok"
    assert payload["services"]["worker"] == "ok"


def test_health_endpoint_reports_errors(monkeypatch) -> None:
    monkeypatch.setattr("app.application.system.health.check_core_database", lambda: False)
    monkeypatch.setattr("app.application.system.health.check_memory_database", lambda: True)
    monkeypatch.setattr("app.application.system.health.check_redis", lambda: True)
    monkeypatch.setattr("app.application.system.health.check_worker", lambda: False)

    client = TestClient(create_app())
    payload = client.get("/api/v1/system/health").json()
    assert payload["status"] == "error"
    assert payload["services"]["core_database"] == "error"
    assert payload["services"]["worker"] == "error"


def test_info_endpoint() -> None:
    client = TestClient(create_app())
    payload = client.get("/api/v1/system/info").json()
    assert payload["name"] == "ProjectAI"
    assert payload["api_version"] == "v1"
