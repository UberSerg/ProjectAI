"""Focused tests for Intelligence Stack V1 shared contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.modules.intelligence.contracts.committee import (
    ADVISORY_STATES,
    COMMITTEE_POLICY_VERSION,
    CommitteeDecisionV1,
    ModelVote,
)
from app.modules.intelligence.contracts.knowledge import KnowledgeRuleEvaluation
from app.modules.intelligence.contracts.provenance import known_at_allows
from app.modules.intelligence.contracts.risk import RiskAssessmentV1
from app.modules.intelligence.contracts.signal import (
    SIGNAL_STATES,
    SignalOutputV1,
    abstain_signal,
    unknown_signal,
)
from app.modules.intelligence.contracts.snapshot import IntelligenceSnapshotV1
from app.modules.intelligence.isolation import (
    EXPECTED_ACTIVE_DATASET,
    EXPECTED_CANDIDATE_DATASET,
    assert_production_isolation,
    production_isolation_report,
)


def test_signal_states_and_score_bounds() -> None:
    assert "UNKNOWN" in SIGNAL_STATES
    assert "ABSTAIN" in SIGNAL_STATES
    ok = SignalOutputV1(
        model_id="TechnicalModelV1",
        model_version="1",
        semantic="TECHNICAL",
        instrument_id=1,
        as_of=date(2026, 10, 1),
        known_at=date(2026, 10, 1),
        horizon="20d",
        state="POSITIVE",
        score=0.4,
        confidence=0.5,
        confidence_semantic="EVIDENCE_COMPLETENESS",
    )
    assert ok.to_dict()["state"] == "POSITIVE"
    with pytest.raises(ValueError):
        SignalOutputV1(
            model_id="x",
            model_version="1",
            semantic="TECHNICAL",
            instrument_id=1,
            as_of=date(2026, 10, 1),
            known_at=None,
            horizon="20d",
            state="BUY",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        SignalOutputV1(
            model_id="x",
            model_version="1",
            semantic="TECHNICAL",
            instrument_id=1,
            as_of=date(2026, 10, 1),
            known_at=None,
            horizon="20d",
            state="POSITIVE",
            score=1.5,
        )
    with pytest.raises(ValueError):
        SignalOutputV1(
            model_id="x",
            model_version="1",
            semantic="TECHNICAL",
            instrument_id=1,
            as_of=date(2026, 10, 1),
            known_at=None,
            horizon="20d",
            state="POSITIVE",
            model_metadata={"order": {"side": "BUY"}},
        )


def test_abstain_and_unknown_helpers() -> None:
    a = abstain_signal(
        model_id="EventModelV1",
        model_version="1",
        semantic="EVENT",
        instrument_id=2,
        as_of=date(2026, 10, 1),
        reason="no_valid_events",
    )
    assert a.state == "ABSTAIN"
    u = unknown_signal(
        model_id="FundamentalModelV1",
        model_version="1",
        semantic="FUNDAMENTAL",
        instrument_id=2,
        as_of=date(2026, 10, 1),
        reason="bank_industrial_ratios_unsupported",
    )
    assert u.state == "UNKNOWN"


def test_pit_known_at_gate() -> None:
    as_of = date(2026, 8, 27)
    assert known_at_allows(as_of, date(2026, 8, 27))
    assert not known_at_allows(as_of, date(2026, 8, 28))
    assert not known_at_allows(as_of, None)
    assert known_at_allows(
        as_of, datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    )


def test_committee_preserves_disagreement_fields() -> None:
    assert "ABSTAIN" in ADVISORY_STATES
    decision = CommitteeDecisionV1(
        as_of=date(2026, 10, 1),
        instrument_id=1,
        advisory_state="HOLD",
        confidence=0.4,
        consensus_strength=0.3,
        disagreement_score=0.7,
        independent_model_votes=(
            ModelVote("TechnicalModelV1", "POSITIVE", 0.5, 0.6),
            ModelVote("FundamentalModelV1", "NEGATIVE", -0.4, 0.5),
        ),
        primary_drivers=("technical_trend",),
        counterarguments=("fundamental_deterioration",),
        what_would_change_decision=("fundamental_stabilization",),
    )
    assert decision.committee_policy_version == COMMITTEE_POLICY_VERSION
    payload = decision.to_dict()
    assert payload["disagreement_score"] == 0.7
    assert len(payload["independent_model_votes"]) == 2


def test_risk_and_snapshot_roundtrip() -> None:
    risk = RiskAssessmentV1(
        as_of=date(2026, 10, 1),
        instrument_id=1,
        risk_state="ELEVATED",
        risk_score=0.6,
        risk_flags=("stale_fundamentals",),
        limitations=("scenario_not_forecast",),
    )
    snap = IntelligenceSnapshotV1(
        instrument_id=1,
        symbol="SBER",
        as_of=date(2026, 10, 1),
        risk=risk,
        limitations=("advisory_only",),
        production_isolation=production_isolation_report(),
    )
    d = snap.to_dict()
    assert d["schema"] == "IntelligenceSnapshotV1"
    assert d["risk"]["risk_state"] == "ELEVATED"
    assert d["production_isolation"]["persist_registry"] is False


def test_knowledge_rule_eval_states() -> None:
    ev = KnowledgeRuleEvaluation(
        rule_id="momentum_needs_volume",
        rule_version="1",
        state="TRIGGERED",
        why="volume confirmation present",
    )
    assert ev.to_dict()["state"] == "TRIGGERED"
    with pytest.raises(ValueError):
        KnowledgeRuleEvaluation(
            rule_id="x",
            rule_version="1",
            state="BUY",  # type: ignore[arg-type]
            why="no",
        )


def test_production_isolation_pins() -> None:
    report = production_isolation_report()
    assert report["pit_daily_core_active_version"] == EXPECTED_ACTIVE_DATASET
    assert report["candidate_v0_dataset_spec_version"] == EXPECTED_CANDIDATE_DATASET
    assert report["candidate_v1_dataset_spec_version"] == EXPECTED_CANDIDATE_DATASET
    assert_production_isolation()
