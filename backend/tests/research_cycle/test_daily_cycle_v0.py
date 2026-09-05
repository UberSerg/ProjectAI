"""Daily Research Cycle V0 — orchestration unit tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from app.modules.research_cycle.config import CYCLE_STEPS
from app.modules.research_cycle.watermarks import determine_health, relations_due
from app.modules.shadow.application.execution_eligibility import (
    is_execution_date_eligible,
    min_execution_market_date,
)


def test_cycle_step_order() -> None:
    assert CYCLE_STEPS[0] == "SOURCE_DISCOVERY"
    assert CYCLE_STEPS[-1] == "FINALIZE"
    assert "FORWARD_SIGNAL" in CYCLE_STEPS
    assert CYCLE_STEPS.index("SHADOW_ADVANCE") > CYCLE_STEPS.index("FORWARD_SIGNAL")
    assert CYCLE_STEPS.index("PROSPECTIVE_MODEL_AB") > CYCLE_STEPS.index("SHADOW_ADVANCE")
    assert CYCLE_STEPS.index("PROSPECTIVE_MODEL_AB_SHADOW") > CYCLE_STEPS.index(
        "PROSPECTIVE_MODEL_AB"
    )
    assert CYCLE_STEPS.index("FORWARD_OUTCOME_EVALUATION") > CYCLE_STEPS.index(
        "PROSPECTIVE_MODEL_AB_SHADOW"
    )
    assert CYCLE_STEPS.index("PROSPECTIVE_MODEL_AB_OUTCOME") > CYCLE_STEPS.index(
        "FORWARD_OUTCOME_EVALUATION"
    )


def test_health_waiting_and_lagging() -> None:
    assert determine_health({"raw_market_latest_date": None}) == "WAITING_FOR_MARKET"
    assert (
        determine_health(
            {
                "raw_market_latest_date": date(2026, 9, 5),
                "analytics_v2_latest_date": date(2026, 9, 2),
                "technical_v2_latest_date": date(2026, 9, 2),
                "forward_latest_as_of": date(2026, 9, 2),
            }
        )
        == "LAGGING"
    )
    assert determine_health({}, running=True) == "RUNNING"
    assert determine_health({}, blocked=True) == "BLOCKED"


def test_relations_due_skipped_when_fresh() -> None:
    session = MagicMock()
    with patch("app.modules.research_cycle.watermarks._relations_v2_latest", return_value=date(2026, 9, 1)):
        due, reason = relations_due(session, date(2026, 9, 2))
        assert due is False
        assert reason == "SKIPPED_NOT_DUE"


def test_relations_due_when_missing() -> None:
    session = MagicMock()
    with patch("app.modules.research_cycle.watermarks._relations_v2_latest", return_value=None):
        due, reason = relations_due(session, date(2026, 9, 2))
        assert due is True
        assert reason == "missing_snapshot"


def test_old_pending_order_can_fill_on_new_open() -> None:
    from datetime import UTC, datetime

    decision_at = datetime(2026, 9, 4, 14, 15, 29, tzinfo=UTC)
    min_d = min_execution_market_date(decision_at)
    assert min_d == date(2026, 9, 5)
    assert is_execution_date_eligible(decision_at=decision_at, market_date=date(2026, 9, 5)) is True
    assert is_execution_date_eligible(decision_at=decision_at, market_date=date(2026, 9, 3)) is False
    assert is_execution_date_eligible(decision_at=decision_at, market_date=date(2026, 9, 4)) is False


def test_same_cycle_new_order_cannot_use_same_day_open() -> None:
    """New decision made after ingesting day D cannot fill at D OPEN."""
    from datetime import UTC, datetime

    # Decision created on D after market close processing → min exec is D+1
    decision_at = datetime(2026, 9, 5, 18, 0, 0, tzinfo=UTC)
    market_day_d = date(2026, 9, 5)
    min_d = min_execution_market_date(decision_at)
    assert min_d == date(2026, 9, 6)
    assert is_execution_date_eligible(decision_at=decision_at, market_date=market_day_d) is False


@patch("app.modules.research_cycle.cycle.try_acquire_cycle_lock")
def test_locking_blocks_second_run(mock_lock: MagicMock) -> None:
    from app.modules.research_cycle.cycle import run_daily_research_cycle

    handle = MagicMock()
    handle.acquired = False
    mock_lock.return_value = handle
    session = MagicMock()
    result = run_daily_research_cycle(session)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "ALREADY_RUNNING"


def test_research_cycle_api_status_contract() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/v1/research-cycle/status")
    assert response.status_code == 200
    payload = response.json()
    assert "health" in payload
    assert "watermarks" in payload
    assert "schedule" in payload
    assert payload["schedule"]["enabled"] is False
