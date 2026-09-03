"""API tests for Relations Engine."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def test_relations_overview(monkeypatch) -> None:
    from app.api.v1 import relations as rel_api

    mock_session = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False
    monkeypatch.setattr(rel_api, "core_session", lambda: mock_cm)
    monkeypatch.setattr(rel_api, "seed_relation_sets", lambda _s: {"ensured": 1})

    active = MagicMock()
    active.id = uuid4()
    active.code = "basic_relations"
    active.version = 1
    active.description = "V1"
    active.parameters = {"windows": [20, 60, 120]}
    active.is_active = True

    # scalar calls in order: active set, inputs_active, snapshots_total, latest_as_of, last_run, valid, invalid
    mock_session.scalar.side_effect = [active, 48, 100, date(2026, 8, 28), None, 90, 10]

    client = TestClient(app)
    resp = client.get("/api/v1/relations/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_relation_set"]["code"] == "basic_relations"
    assert body["inputs_active"] == 48
    assert body["quality"]["valid"] == 90


def test_compute_latest_starts_workflow(monkeypatch) -> None:
    from app.api.v1 import relations as rel_api

    mock_session = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False
    monkeypatch.setattr(rel_api, "core_session", lambda: mock_cm)

    rs = MagicMock()
    rs.code = "basic_relations"
    rs.version = 1
    monkeypatch.setattr(rel_api, "resolve_relation_set", lambda *_a, **_k: rs)

    wf = MagicMock()
    wf.id = 42
    monkeypatch.setattr(rel_api, "create_workflow", lambda *_a, **_k: wf)

    delay = MagicMock()
    monkeypatch.setattr(rel_api.worker_tasks.relations_compute_latest, "delay", delay)

    client = TestClient(app)
    resp = client.post("/api/v1/relations/compute-latest", json={})
    assert resp.status_code == 200
    assert resp.json()["workflow_id"] == 42
    delay.assert_called_once()


def test_backfill_rejects_bad_cadence() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/relations/backfill",
        json={"as_of_from": "2026-01-01", "cadence": "HOURLY"},
    )
    assert resp.status_code == 400


def test_overview_and_snapshots_accept_relation_set_version(monkeypatch) -> None:
    from app.api.v1 import relations as rel_api

    mock_session = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False
    monkeypatch.setattr(rel_api, "core_session", lambda: mock_cm)
    monkeypatch.setattr(rel_api, "seed_relation_sets", lambda _s: {"ensured": 2})

    captured: dict[str, object] = {}

    class _Set:
        id = uuid4()
        code = "basic_relations"
        version = 2
        description = "V2"
        parameters = {"analytics_feature_set_version": 2}
        is_active = False

    chosen = _Set()

    def _resolve(_session, code, version=None):
        captured["code"] = code
        captured["version"] = version
        return chosen

    monkeypatch.setattr(rel_api, "resolve_relation_set", _resolve)

    active = MagicMock()
    active.id = uuid4()
    active.code = "basic_relations"
    active.version = 1
    active.description = "V1"
    active.parameters = {"windows": [20, 60, 120]}
    active.is_active = True
    mock_session.scalar.side_effect = [active, 48, 10, date(2026, 8, 28), None, 8, 2]

    client = TestClient(app)
    overview = client.get("/api/v1/relations/overview", params={"relation_set_version": 2})
    assert overview.status_code == 200
    assert captured["version"] == 2

    mock_session.scalars.return_value = []
    mock_session.scalar.side_effect = [date(2026, 8, 28)]
    snaps = client.get(
        "/api/v1/relations/snapshots",
        params={"relation_set_code": "basic_relations", "relation_set_version": 2},
    )
    assert snaps.status_code == 200
    assert captured["version"] == 2
