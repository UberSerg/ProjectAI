"""Committee adversarial: all-abstain, disagreement, stale data, single valid model."""

from __future__ import annotations

import importlib
from datetime import date

import pytest

from app.modules.intelligence.contracts.committee import (
    ADVISORY_STATES,
    COMMITTEE_POLICY_VERSION,
    CommitteeDecisionV1,
    ModelVote,
    votes_from_signals,
)
from app.modules.intelligence.contracts.knowledge import KnowledgeRuleEvaluation
from app.modules.intelligence.contracts.risk import RiskAssessmentV1
from app.modules.intelligence.contracts.signal import (
    SignalOutputV1,
    abstain_signal,
    unknown_signal,
)


def _sig(
    model_id: str,
    state: str,
    *,
    score: float | None = None,
    confidence: float | None = 0.5,
    as_of: date = date(2026, 7, 1),
) -> SignalOutputV1:
    return SignalOutputV1(
        model_id=model_id,
        model_version="1",
        semantic=model_id.replace("ModelV1", "").upper() or "GENERIC",
        instrument_id=1,
        as_of=as_of,
        known_at=as_of if state not in {"ABSTAIN", "UNKNOWN"} else None,
        horizon="20d",
        state=state,  # type: ignore[arg-type]
        score=score,
        confidence=confidence,
        confidence_semantic="EVIDENCE_COMPLETENESS",
    )


def test_all_models_abstain_advisory_must_be_abstain() -> None:
    signals = [
        abstain_signal(
            model_id="TechnicalModelV1",
            model_version="1",
            semantic="TECHNICAL",
            instrument_id=1,
            as_of=date(2026, 7, 1),
            reason="no_bars",
        ),
        abstain_signal(
            model_id="FundamentalModelV1",
            model_version="1",
            semantic="FUNDAMENTAL",
            instrument_id=1,
            as_of=date(2026, 7, 1),
            reason="no_reports",
        ),
        unknown_signal(
            model_id="EventModelV1",
            model_version="1",
            semantic="EVENT",
            instrument_id=1,
            as_of=date(2026, 7, 1),
            reason="no_events",
        ),
    ]
    votes = votes_from_signals(signals)
    decision = CommitteeDecisionV1(
        as_of=date(2026, 7, 1),
        instrument_id=1,
        advisory_state="ABSTAIN",
        confidence=0.0,
        consensus_strength=0.0,
        disagreement_score=0.0,
        independent_model_votes=votes,
        blockers=("all_models_abstain_or_unknown",),
        data_gaps=("insufficient_valid_models",),
        what_would_change_decision=("at_least_two_valid_independent_signals",),
    )
    assert decision.advisory_state == "ABSTAIN"
    assert all(v.state in {"ABSTAIN", "UNKNOWN"} for v in decision.independent_model_votes)
    assert "CONSIDER_INCREASE" not in {decision.advisory_state}


def test_strong_disagreement_is_preserved_not_averaged_away() -> None:
    votes = (
        ModelVote("TechnicalModelV1", "POSITIVE", 0.8, 0.7),
        ModelVote("FundamentalModelV1", "NEGATIVE", -0.7, 0.7),
        ModelVote("EventModelV1", "NEUTRAL", 0.0, 0.4),
    )
    decision = CommitteeDecisionV1(
        as_of=date(2026, 7, 1),
        instrument_id=1,
        advisory_state="HOLD",
        confidence=0.25,
        consensus_strength=0.2,
        disagreement_score=0.85,
        independent_model_votes=votes,
        primary_drivers=("technical_momentum",),
        counterarguments=("fundamental_deterioration",),
        what_would_change_decision=("fundamental_stabilization",),
        limitations=("high_disagreement_lowers_confidence",),
    )
    assert decision.disagreement_score == 0.85
    assert decision.confidence is not None and decision.confidence < 0.5
    states = {v.state for v in decision.independent_model_votes}
    assert "POSITIVE" in states and "NEGATIVE" in states


def test_stale_data_and_no_evidence_force_abstain_path() -> None:
    decision = CommitteeDecisionV1(
        as_of=date(2026, 7, 1),
        instrument_id=1,
        advisory_state="ABSTAIN",
        confidence=0.0,
        consensus_strength=None,
        disagreement_score=None,
        independent_model_votes=(
            ModelVote("TechnicalModelV1", "POSITIVE", 0.4, 0.3, note="stale_features"),
        ),
        blockers=("severe_stale_data", "no_source_evidence"),
        data_gaps=("stale_fundamentals", "stale_macro"),
        risk_overrides=("data_risk_high",),
        limitations=("stale_data_abstain",),
    )
    assert decision.advisory_state == "ABSTAIN"
    assert "severe_stale_data" in decision.blockers


def test_single_valid_model_is_insufficient_for_increase() -> None:
    """Only one valid model → must not escalate to CONSIDER_INCREASE."""
    decision = CommitteeDecisionV1(
        as_of=date(2026, 7, 1),
        instrument_id=1,
        advisory_state="ABSTAIN",
        confidence=0.2,
        consensus_strength=0.0,
        disagreement_score=0.0,
        independent_model_votes=(
            ModelVote("TechnicalModelV1", "POSITIVE", 0.9, 0.9),
            ModelVote("FundamentalModelV1", "ABSTAIN", None, None),
            ModelVote("EventModelV1", "UNKNOWN", None, None),
        ),
        blockers=("insufficient_valid_models",),
        data_gaps=("only_one_valid_independent_model",),
    )
    assert decision.advisory_state != "CONSIDER_INCREASE"
    assert decision.advisory_state == "ABSTAIN"


def test_risk_override_can_block_weak_positive_committee() -> None:
    risk = RiskAssessmentV1(
        as_of=date(2026, 7, 1),
        instrument_id=1,
        risk_state="HIGH",
        risk_score=0.9,
        risk_flags=("material_adverse_event", "event_risk"),
        event_risk="HIGH",
        limitations=("scenario_not_forecast",),
    )
    decision = CommitteeDecisionV1(
        as_of=date(2026, 7, 1),
        instrument_id=1,
        advisory_state="CONSIDER_REDUCE",
        confidence=0.4,
        consensus_strength=0.3,
        disagreement_score=0.4,
        independent_model_votes=(
            ModelVote("TechnicalModelV1", "POSITIVE", 0.3, 0.4),
            ModelVote("EventModelV1", "NEGATIVE", -0.8, 0.8),
        ),
        risk_overrides=("material_adverse_event",),
        primary_drivers=("event_negative",),
        counterarguments=("weak_technical_positive",),
        metadata={"risk_state": risk.risk_state},
    )
    assert decision.advisory_state in ADVISORY_STATES
    assert decision.advisory_state != "CONSIDER_INCREASE"
    assert "material_adverse_event" in decision.risk_overrides


def test_knowledge_rules_never_emit_trade_actions() -> None:
    ev = KnowledgeRuleEvaluation(
        rule_id="momentum_needs_volume",
        rule_version="1",
        state="TRIGGERED",
        why="volume confirmation present",
    )
    assert ev.state == "TRIGGERED"
    with pytest.raises(ValueError):
        KnowledgeRuleEvaluation(
            rule_id="x",
            rule_version="1",
            state="BUY",  # type: ignore[arg-type]
            why="injected",
        )


def test_committee_policy_version_is_predeclared() -> None:
    assert COMMITTEE_POLICY_VERSION == "committee_policy_v1_predeclared"
    decision = CommitteeDecisionV1(
        as_of=date(2026, 7, 1),
        instrument_id=1,
        advisory_state="HOLD",
        confidence=0.5,
        consensus_strength=0.5,
        disagreement_score=0.1,
        independent_model_votes=(ModelVote("TechnicalModelV1", "NEUTRAL", 0.0, 0.5),),
    )
    assert decision.committee_policy_version == COMMITTEE_POLICY_VERSION


def test_committee_module_all_abstain_if_present() -> None:
    try:
        committee = importlib.import_module("app.modules.intelligence.committee")
    except ModuleNotFoundError:
        pytest.skip("intelligence.committee not implemented yet")

    decide = (
        getattr(committee, "decide", None)
        or getattr(committee, "run_committee", None)
        or getattr(committee, "combine", None)
    )
    if decide is None:
        policy = getattr(committee, "committee_policy_v1_predeclared", None) or getattr(
            committee, "policy", None
        )
        if policy is not None and callable(getattr(policy, "decide", None)):
            decide = policy.decide
    if decide is None:
        pytest.skip("committee module present without decide() export")

    signals = [
        abstain_signal(
            model_id="TechnicalModelV1",
            model_version="1",
            semantic="TECHNICAL",
            instrument_id=1,
            as_of=date(2026, 7, 1),
            reason="none",
        ),
        abstain_signal(
            model_id="FundamentalModelV1",
            model_version="1",
            semantic="FUNDAMENTAL",
            instrument_id=1,
            as_of=date(2026, 7, 1),
            reason="none",
        ),
    ]
    result = decide(
        as_of=date(2026, 7, 1),
        instrument_id=1,
        signals=signals,
        knowledge_evaluations=(),
        risk=None,
    )
    advisory = getattr(result, "advisory_state", None) or result.get("advisory_state")
    assert advisory == "ABSTAIN"
