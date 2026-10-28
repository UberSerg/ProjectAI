"""Counterfactual provenance propagates batch → decision metadata shape."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.modules.shadow.application.history_provenance import (
    HISTORY_KIND_COUNTERFACTUAL,
    HISTORY_KIND_RECORDED_LIVE,
    batch_history_kind,
    provenance_from_batch,
)


def test_recorded_live_batch_kind() -> None:
    batch = SimpleNamespace(id=1, as_of_date=date(2026, 9, 1), input_lineage={})
    assert batch_history_kind(batch) == HISTORY_KIND_RECORDED_LIVE
    prov = provenance_from_batch(batch, policy_name="p", risk_name="r")
    assert prov["history_kind"] == HISTORY_KIND_RECORDED_LIVE
    assert prov["reconstruction"] is False
    assert prov["forward_batch_id"] == 1
    assert "reconstructed_at" not in prov


def test_counterfactual_batch_kind() -> None:
    batch = SimpleNamespace(
        id=9,
        as_of_date=date(2026, 9, 15),
        input_lineage={
            "history_kind": HISTORY_KIND_COUNTERFACTUAL,
            "reconstruction": True,
            "reconstructed_at": "2026-10-28T12:00:00+00:00",
            "pit_visibility_clock": "2026-09-15T18:00:00+00:00",
        },
    )
    assert batch_history_kind(batch) == HISTORY_KIND_COUNTERFACTUAL
    prov = provenance_from_batch(
        batch,
        session_date=date(2026, 9, 15),
        policy_name="rank_v1",
        risk_name="dd_guard",
        execution_version="lot_v2",
    )
    assert prov["history_kind"] == HISTORY_KIND_COUNTERFACTUAL
    assert prov["reconstructed_at"] == "2026-10-28T12:00:00+00:00"
    assert prov["pit_visibility_clock"] == "2026-09-15T18:00:00+00:00"
    assert prov["policy_name"] == "rank_v1"
    assert prov["execution_version"] == "lot_v2"
