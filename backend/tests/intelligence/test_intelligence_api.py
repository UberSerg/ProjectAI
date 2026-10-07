"""API tests for Company Intelligence endpoints."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.main import create_app


@pytest.fixture
def client(core_db: Session, monkeypatch) -> TestClient:
    @contextmanager
    def _fake_core_session():
        yield core_db

    monkeypatch.setattr("app.api.v1.intelligence.core_session", _fake_core_session)
    monkeypatch.setattr("app.infrastructure.db.session.core_session", _fake_core_session)
    return TestClient(create_app())


@pytest.fixture
def instrument(core_db: Session) -> Instrument:
    inst = Instrument(
        symbol="INTELTEST",
        name="Intelligence Test Equity",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
    )
    core_db.add(inst)
    core_db.flush()
    return inst


def test_snapshot_endpoint_unknown_coverage(client: TestClient, instrument: Instrument) -> None:
    resp = client.get(
        f"/api/v1/intelligence/instruments/{instrument.id}",
        params={"as_of": "2026-10-01"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["schema"] == "IntelligenceSnapshotV1"
    assert data["instrument_id"] == instrument.id
    assert data["symbol"] == "INTELTEST"
    assert data["as_of"] == "2026-10-01"
    assert all(s["state"] == "UNKNOWN" for s in data["signals"])
    assert data["committee"]["advisory_state"] == "ABSTAIN"
    assert data["committee"]["what_would_change_decision"]
    assert data["risk"]["risk_state"] == "UNKNOWN"
    assert data["production_isolation"]["persist_registry"] is False


def test_subresources_and_refresh_stub(client: TestClient, instrument: Instrument) -> None:
    iid = instrument.id
    signals = client.get(f"/api/v1/intelligence/instruments/{iid}/signals")
    assert signals.status_code == 200
    assert len(signals.json()["signals"]) >= 1

    events = client.get(f"/api/v1/intelligence/instruments/{iid}/events")
    assert events.status_code == 200
    assert events.json()["coverage_status"] in {"UNKNOWN", "NOT_READY", "PARTIAL"}

    fundamentals = client.get(f"/api/v1/intelligence/instruments/{iid}/fundamentals")
    assert fundamentals.status_code == 200
    # With a DB session, industrial FNS may return READY/PARTIAL/NOT_AVAILABLE;
    # without wired facts it stays UNKNOWN. Never invent NEUTRAL/zero.
    assert fundamentals.json()["fundamentals_summary"]["status"] in {
        "UNKNOWN",
        "NOT_AVAILABLE",
        "PARTIAL",
        "READY",
    }

    committee = client.get(f"/api/v1/intelligence/instruments/{iid}/committee")
    assert committee.status_code == 200
    assert committee.json()["committee"]["advisory_state"] == "ABSTAIN"

    refresh = client.post(
        f"/api/v1/intelligence/instruments/{iid}/refresh",
        json={"as_of": "2026-10-01", "force": False},
    )
    assert refresh.status_code == 200
    body = refresh.json()
    assert body["status"] == "STUBBED"
    assert body["accepted"] is False
    assert body["production_isolation"]["broker_execution"] is False


def test_missing_instrument_404(client: TestClient) -> None:
    resp = client.get("/api/v1/intelligence/instruments/999999999")
    assert resp.status_code == 404
