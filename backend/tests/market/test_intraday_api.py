"""Intraday status API contract."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_intraday_status_contract() -> None:
    response = client.get("/api/v1/market/intraday/status")
    assert response.status_code == 200
    payload = response.json()
    assert "enabled" in payload
    assert payload["writes_market_candles"] is False
    assert payload["persistence"] == "redis_ephemeral_only"
    assert payload["policy"] == "SHADOW_NEXT_SESSION_OPEN_V1"


def test_shadow_overview_includes_intraday_block() -> None:
    response = client.get("/api/v1/shadow/overview")
    assert response.status_code == 200
    payload = response.json()
    assert "intraday" in payload
    assert "enabled" in payload["intraday"]
    assert payload["intraday"]["policy"] == "SHADOW_NEXT_SESSION_OPEN_V1"
