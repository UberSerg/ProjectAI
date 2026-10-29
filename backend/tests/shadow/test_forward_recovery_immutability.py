"""P0: recovery must not rewrite recorded LIVE Forward batch lineage."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.shadow.application.recovery import (
    HISTORY_KIND_COUNTERFACTUAL,
    HISTORY_KIND_RECORDED_LIVE,
    _backfill_forward_as_of,
    _batch_history_kind,
)


def _fwd(status: str, batch_id: int | None, as_of: date, summary: dict | None = None):
    return SimpleNamespace(status=status, batch_id=batch_id, as_of=as_of, summary=summary or {})


def test_no_changes_live_batch_is_not_mutated() -> None:
    session = MagicMock()
    live_batch = SimpleNamespace(
        id=42,
        input_lineage={"pins": {"candidate": "v0"}, "history_kind": None},
    )
    # Preserve a sentinel to detect mutation.
    live_batch.input_lineage["sentinel"] = "LIVE_UNTOUCHED"
    session.get.return_value = live_batch

    with patch(
        "app.modules.shadow.application.recovery.run_forward_signal_v0",
        return_value=_fwd("NO_CHANGES", 42, date(2026, 9, 8), {"immutable": True}),
    ):
        rows = _backfill_forward_as_of(session, [date(2026, 9, 8)])

    assert rows[0]["status"] == "NO_CHANGES"
    assert rows[0]["history_kind"] == HISTORY_KIND_RECORDED_LIVE
    assert rows[0]["lineage_mutated"] is False
    assert live_batch.input_lineage["sentinel"] == "LIVE_UNTOUCHED"
    assert live_batch.input_lineage.get("reconstruction") is not True


def test_existing_counterfactual_no_changes_keeps_reconstructed_at() -> None:
    session = MagicMock()
    cf_batch = SimpleNamespace(
        id=7,
        input_lineage={
            "history_kind": HISTORY_KIND_COUNTERFACTUAL,
            "reconstruction": True,
            "reconstructed_at": "2026-10-01T12:00:00+00:00",
        },
    )
    session.get.return_value = cf_batch
    with patch(
        "app.modules.shadow.application.recovery.run_forward_signal_v0",
        return_value=_fwd("NO_CHANGES", 7, date(2026, 9, 8)),
    ):
        rows = _backfill_forward_as_of(session, [date(2026, 9, 8)])
    assert rows[0]["history_kind"] == HISTORY_KIND_COUNTERFACTUAL
    assert cf_batch.input_lineage["reconstructed_at"] == "2026-10-01T12:00:00+00:00"
    assert rows[0]["lineage_mutated"] is False


def test_new_success_batch_is_stamped_counterfactual() -> None:
    session = MagicMock()
    new_batch = SimpleNamespace(id=99, input_lineage={"pins": {"candidate": "v0"}})
    session.get.return_value = new_batch
    with patch(
        "app.modules.shadow.application.recovery.run_forward_signal_v0",
        return_value=_fwd("SUCCESS", 99, date(2026, 9, 8)),
    ):
        rows = _backfill_forward_as_of(session, [date(2026, 9, 8)])
    assert rows[0]["history_kind"] == HISTORY_KIND_COUNTERFACTUAL
    assert rows[0]["lineage_mutated"] is True
    assert new_batch.input_lineage["reconstruction"] is True
    assert new_batch.input_lineage["history_kind"] == HISTORY_KIND_COUNTERFACTUAL
    session.flush.assert_called()


def test_batch_history_kind_defaults_to_recorded_live() -> None:
    assert _batch_history_kind(None) == HISTORY_KIND_RECORDED_LIVE
    assert _batch_history_kind(SimpleNamespace(input_lineage={})) == HISTORY_KIND_RECORDED_LIVE
    assert (
        _batch_history_kind(
            SimpleNamespace(input_lineage={"history_kind": HISTORY_KIND_COUNTERFACTUAL})
        )
        == HISTORY_KIND_COUNTERFACTUAL
    )
