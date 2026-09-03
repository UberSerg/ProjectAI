"""API tests for Technical Agent endpoints."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app
from app.modules.analytics.application.seed import seed_feature_sets


@pytest.fixture
def client(core_db: Session, monkeypatch) -> TestClient:
    @contextmanager
    def _fake_core_session():
        yield core_db

    monkeypatch.setattr("app.api.v1.technical.core_session", _fake_core_session)
    monkeypatch.setattr("app.infrastructure.db.session.core_session", _fake_core_session)
    return TestClient(create_app())


def test_models_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/technical/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["model_code"] == "rules"
    assert data[0]["model_version"] == 1
    assert data[0]["is_active"] is True
    assert "config_hash" in data[0]
    versions = {(row["model_code"], row["model_version"]) for row in data}
    assert ("rules", 1) in versions
    assert ("rules", 2) in versions
    v2 = next(row for row in data if row["model_version"] == 2)
    assert v2["is_active"] is False


def test_overview_emptyish(client: TestClient, core_db: Session) -> None:
    seed_feature_sets(core_db)
    resp = client.get("/api/v1/technical/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_model"] == "rules_v1"
    assert "technical_daily" in body["technical_feature_set"]


def test_signals_pagination_and_bad_confidence(client: TestClient) -> None:
    resp = client.get("/api/v1/technical/signals", params={"limit": 10, "offset": 0})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    bad = client.get("/api/v1/technical/signals", params={"min_confidence": 1.5})
    assert bad.status_code == 422


def test_instrument_latest_unknown(client: TestClient) -> None:
    resp = client.get("/api/v1/technical/instruments/999999/latest")
    assert resp.status_code == 404


def test_backfill_bad_dates(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/technical/backfill",
        json={"date_from": "2024-06-01", "date_to": "2024-01-01"},
    )
    assert resp.status_code == 400


def test_backfill_unknown_model(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/technical/backfill",
        json={"date_from": "2024-01-01", "model_code": "catboost", "model_version": 1},
    )
    assert resp.status_code == 400


@patch("app.worker.tasks.technical_backfill.delay")
def test_backfill_allows_rules_v2(mock_delay: MagicMock, client: TestClient, core_db: Session) -> None:
    seed_feature_sets(core_db)
    resp = client.post(
        "/api/v1/technical/backfill",
        json={"date_from": "2014-01-01", "model_code": "rules", "model_version": 2},
    )
    assert resp.status_code == 200
    assert mock_delay.call_args[0][5] == 2


@patch("app.worker.tasks.technical_update.delay")
def test_update_starts_workflow(mock_delay: MagicMock, client: TestClient, core_db: Session) -> None:
    seed_feature_sets(core_db)
    resp = client.post("/api/v1/technical/update", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert "workflow_id" in body
    mock_delay.assert_called_once()


@patch("app.worker.tasks.technical_backfill.delay")
def test_backfill_starts_workflow(mock_delay: MagicMock, client: TestClient, core_db: Session) -> None:
    seed_feature_sets(core_db)
    resp = client.post(
        "/api/v1/technical/backfill",
        json={"date_from": "2024-01-01", "date_to": "2024-01-31"},
    )
    assert resp.status_code == 200
    mock_delay.assert_called_once()
    args = mock_delay.call_args[0]
    assert args[1] == "2024-01-01"
    assert args[2] == "2024-01-31"
