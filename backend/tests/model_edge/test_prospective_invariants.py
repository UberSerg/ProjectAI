"""Prospective Model A/B isolation and causality tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.modules.model_edge.domain.types import ActivationWatermark
from app.modules.shadow.application.execution_eligibility import (
    is_execution_date_eligible,
    min_execution_market_date,
)


def test_new_orders_cannot_use_same_day_open() -> None:
    """Paired predictions generated after day D completes must not fill at D OPEN."""
    decision_at = datetime(2026, 9, 4, 18, 0, tzinfo=UTC)  # after D=2026-09-04 close
    min_exec = min_execution_market_date(decision_at)
    assert min_exec == date(2026, 9, 5)
    assert is_execution_date_eligible(decision_at=decision_at, market_date=date(2026, 9, 4)) is False
    assert is_execution_date_eligible(decision_at=decision_at, market_date=date(2026, 9, 5)) is True


def test_old_shadow_orders_may_fill_on_new_day_open() -> None:
    """Operational Shadow pending orders created earlier may execute at D OPEN."""
    old_decision = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    market_d = date(2026, 9, 4)
    assert is_execution_date_eligible(decision_at=old_decision, market_date=market_d) is True
    assert market_d >= min_execution_market_date(old_decision)


def test_no_backfill_of_activation_watermark_day() -> None:
    wm = ActivationWatermark(
        activated_at=datetime(2026, 9, 5, 10, 0, tzinfo=UTC),
        market_watermark=date(2026, 9, 3),
    )
    assert wm.allows(date(2026, 9, 3)) is False
    assert wm.allows(date(2026, 9, 3) + timedelta(days=1)) is True


def test_v1_semantic_is_ranking_score_not_return() -> None:
    from app.modules.model_edge.config import (
        SEMANTIC_EXPECTED_RETURN,
        SEMANTIC_RANKING_SCORE,
        semantic_for_candidate_version,
    )
    from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
    from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG

    assert semantic_for_candidate_version(CANDIDATE_V0_CONFIG.candidate_version) == (
        SEMANTIC_EXPECTED_RETURN
    )
    assert semantic_for_candidate_version(CANDIDATE_V1_RANKER_CONFIG.candidate_version) == (
        SEMANTIC_RANKING_SCORE
    )
