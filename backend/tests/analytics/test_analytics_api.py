"""Analytics API integration tests."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def client(core_db: Session, monkeypatch) -> TestClient:
    @contextmanager
    def _fake_core_session():
        yield core_db

    monkeypatch.setattr("app.api.v1.analytics.core_session", _fake_core_session)
    monkeypatch.setattr("app.infrastructure.db.session.core_session", _fake_core_session)
    from app.main import create_app

    return TestClient(create_app())


def test_get_feature_sets_api(client: TestClient) -> None:
    response = client.get("/api/v1/analytics/features/sets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert any(item["code"] == "basic_daily" for item in body["items"])


def test_overview_api(client: TestClient) -> None:
    response = client.get("/api/v1/analytics/overview")
    assert response.status_code == 200
    body = response.json()
    assert "active_feature_set" in body
    assert "instrument_feature_rows" in body
