"""Shadow overview API enrichment for Live Research dashboard."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_shadow_overview_contract() -> None:
    response = client.get("/api/v1/shadow/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "FORWARD_SHADOW"
    assert payload["automatic_schedule"] == "not_configured"
    assert isinstance(payload["portfolios"], list)
    if payload["portfolios"]:
        p = payload["portfolios"][0]
        for key in (
            "id",
            "name",
            "status",
            "cash",
            "nav",
            "pending_orders",
            "fills",
            "experiment_group",
            "initial_capital",
        ):
            assert key in p


def test_shadow_orders_include_display_name_field() -> None:
    portfolios = client.get("/api/v1/shadow/portfolios").json()
    if not portfolios:
        return
    pid = portfolios[0]["id"]
    orders = client.get(f"/api/v1/shadow/portfolios/{pid}/orders").json()
    assert isinstance(orders, list)
    if orders:
        assert "display_name" in orders[0]
        assert "eligible_count" in orders[0]
