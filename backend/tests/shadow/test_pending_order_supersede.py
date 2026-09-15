"""Pending shadow orders are cancelled when a new weekly decision is published."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.modules.shadow.application.service import _cancel_pending_orders


def test_cancel_pending_orders_supersedes_old_pending() -> None:
    decision_at = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    old = SimpleNamespace(
        id=2,
        portfolio_id=5,
        decision_id=90,
        status="PENDING",
        updated_at=None,
        metadata_={"lot_size": 10},
    )
    session = MagicMock()
    # SQL already filters status=PENDING and decision_id != exclude.
    session.scalars.return_value = [old]

    n = _cancel_pending_orders(
        session,
        portfolio_id=5,
        reason="SUPERSEDED_BY_NEW_DECISION",
        decision_at=decision_at,
        exclude_decision_id=100,
    )
    assert n == 1
    assert old.status == "CANCELLED"
    assert old.updated_at == decision_at
    assert old.metadata_["cancel_reason"] == "SUPERSEDED_BY_NEW_DECISION"
    assert old.metadata_["cancelled_at"] == decision_at.isoformat()
    assert old.metadata_["lot_size"] == 10


def test_cancel_pending_orders_zero_when_none() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    n = _cancel_pending_orders(
        session,
        portfolio_id=1,
        reason="SUPERSEDED_BY_NEW_DECISION",
        decision_at=datetime(2026, 9, 8, tzinfo=UTC),
        exclude_decision_id=1,
    )
    assert n == 0
