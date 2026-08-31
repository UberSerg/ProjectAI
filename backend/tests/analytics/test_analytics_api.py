"""Analytics API integration tests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import FeatureSet
from app.infrastructure.market.models import Instrument
from app.modules.analytics.application.seed import seed_feature_sets


@pytest.fixture
def client(core_db: Session, monkeypatch) -> TestClient:
    @contextmanager
    def _fake_core_session():
        yield core_db

    monkeypatch.setattr("app.api.v1.analytics.core_session", _fake_core_session)
    monkeypatch.setattr("app.infrastructure.db.session.core_session", _fake_core_session)
    from app.main import create_app

    return TestClient(create_app())


def _instrument(core_db: Session) -> Instrument:
    row = Instrument(
        symbol="TST",
        name="Test",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
    )
    core_db.add(row)
    core_db.flush()
    return row


def _activate_version(session: Session, code: str, version: int) -> FeatureSet:
    session.execute(update(FeatureSet).where(FeatureSet.code == code).values(is_active=False))
    session.flush()
    row = session.scalar(select(FeatureSet).where(FeatureSet.code == code, FeatureSet.version == version))
    assert row is not None
    row.is_active = True
    session.flush()
    return row


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
    assert "charset=utf-8" in response.headers["content-type"].lower()


def test_latest_features_without_version_uses_active(
    client: TestClient, core_db: Session
) -> None:
    seed_feature_sets(core_db)
    instrument = _instrument(core_db)
    response = client.get(f"/api/v1/analytics/instruments/{instrument.id}/features/latest")
    # No rows yet, but resolution must succeed for active v1 (404 = no features, not set).
    assert response.status_code == 404
    assert "No features" in response.json()["detail"]


def test_latest_features_explicit_version_and_missing(
    client: TestClient, core_db: Session
) -> None:
    seed_feature_sets(core_db)
    instrument = _instrument(core_db)
    ok = client.get(
        f"/api/v1/analytics/instruments/{instrument.id}/features/latest",
        params={"feature_set_code": "basic_daily", "feature_set_version": 1},
    )
    assert ok.status_code == 404
    assert "No features" in ok.json()["detail"]

    missing = client.get(
        f"/api/v1/analytics/instruments/{instrument.id}/features/latest",
        params={"feature_set_code": "basic_daily", "feature_set_version": 99},
    )
    assert missing.status_code == 404
    assert "Feature set not found" in missing.json()["detail"]


def test_latest_features_follows_active_v2(client: TestClient, core_db: Session) -> None:
    seed_feature_sets(core_db)
    v2 = FeatureSet(
        code="basic_daily",
        version=2,
        description="v2",
        parameters={},
        is_active=False,
        updated_at=datetime.now(UTC),
    )
    core_db.add(v2)
    core_db.flush()
    _activate_version(core_db, "basic_daily", 2)
    instrument = _instrument(core_db)
    response = client.get(
        f"/api/v1/analytics/instruments/{instrument.id}/features/latest",
        params={"feature_set_code": "basic_daily"},
    )
    assert response.status_code == 404
    assert "No features" in response.json()["detail"]

    inactive_only = client.get(
        f"/api/v1/analytics/instruments/{instrument.id}/features/latest",
        params={"feature_set_code": "basic_daily", "feature_set_version": 1},
    )
    assert inactive_only.status_code == 404
    assert "No features" in inactive_only.json()["detail"]
