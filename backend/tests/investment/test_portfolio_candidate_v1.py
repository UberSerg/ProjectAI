"""Portfolio Candidate V1 domain helpers still valid after concrete composition."""

from __future__ import annotations

from app.modules.investment.domain.portfolio_candidate import (
    classify_candidate_status,
    human_confidence_label,
)


def test_human_confidence_unknown_is_plain_russian() -> None:
    assert human_confidence_label("UNKNOWN") == "Недостаточно данных"
    assert human_confidence_label("INSUFFICIENT_SAMPLE") == "Недостаточно данных"


def test_classify_statuses() -> None:
    assert (
        classify_candidate_status(
            gate_status="APPROVED", has_positions=True, stale=False, insufficient=False
        ).value
        == "READY_FOR_RESEARCH"
    )
    assert (
        classify_candidate_status(
            gate_status="BLOCKED", has_positions=False, stale=False, insufficient=False
        ).value
        == "BLOCKED_BY_RISK"
    )
    assert (
        classify_candidate_status(
            gate_status="RESEARCH_ONLY", has_positions=False, stale=False, insufficient=False
        ).value
        == "PARTIAL"
    )
    assert (
        classify_candidate_status(
            gate_status="RESEARCH_ONLY", has_positions=True, stale=True, insufficient=False
        ).value
        == "STALE"
    )
