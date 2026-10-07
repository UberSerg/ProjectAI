"""Focused adversarial tests for committee_policy_v1_predeclared."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.intelligence.committee import POLICY_VERSION, SEMANTIC_WEIGHTS, decide
from app.modules.intelligence.committee.policy_v1 import (
    HIGH_DISAGREEMENT,
    MIN_VALID_MODELS,
)
from app.modules.intelligence.contracts.committee import COMMITTEE_POLICY_VERSION
from app.modules.intelligence.contracts.knowledge import KnowledgeRuleEvaluation
from app.modules.intelligence.contracts.risk import RiskAssessmentV1
from app.modules.intelligence.contracts.signal import SignalOutputV1, abstain_signal

AS_OF = date(2026, 10, 1)
INSTRUMENT = 42


def _sig(
    *,
    model_id: str,
    semantic: str,
    state: str,
    score: float | None = None,
    confidence: float | None = 0.7,
    data_freshness: str | None = "FRESH",
) -> SignalOutputV1:
    return SignalOutputV1(
        model_id=model_id,
        model_version="1",
        semantic=semantic,
        instrument_id=INSTRUMENT,
        as_of=AS_OF,
        known_at=AS_OF,
        horizon="20d",
        state=state,  # type: ignore[arg-type]
        score=score,
        confidence=confidence,
        data_freshness=data_freshness,
    )


def test_policy_version_is_predeclared_contract() -> None:
    assert POLICY_VERSION == COMMITTEE_POLICY_VERSION == "committee_policy_v1_predeclared"
    # Equal predeclared weights — no outcome-tuned asymmetry.
    assert len(set(SEMANTIC_WEIGHTS.values())) == 1
    assert next(iter(SEMANTIC_WEIGHTS.values())) == 1.0


def test_all_abstain_yields_abstain() -> None:
    signals = [
        abstain_signal(
            model_id="TechnicalModelV1",
            model_version="1",
            semantic="TECHNICAL",
            instrument_id=INSTRUMENT,
            as_of=AS_OF,
            reason="no_bars",
        ),
        abstain_signal(
            model_id="FundamentalModelV1",
            model_version="1",
            semantic="FUNDAMENTAL",
            instrument_id=INSTRUMENT,
            as_of=AS_OF,
            reason="missing_filings",
        ),
        abstain_signal(
            model_id="EventModelV1",
            model_version="1",
            semantic="EVENT",
            instrument_id=INSTRUMENT,
            as_of=AS_OF,
            reason="no_events",
        ),
    ]
    decision = decide(as_of=AS_OF, instrument_id=INSTRUMENT, signals=signals)
    assert decision.advisory_state == "ABSTAIN"
    assert decision.metadata["abstain_reason"] == "insufficient_valid_models"
    assert "insufficient_valid_models" in decision.blockers
    assert decision.confidence is None
    assert decision.committee_policy_version == POLICY_VERSION
    assert decision.metadata.get("issues_trades") is False
    payload = decision.to_dict()
    assert "order" not in payload
    assert "orders" not in payload


def test_one_model_only_abstains() -> None:
    assert MIN_VALID_MODELS == 2
    signals = [
        _sig(
            model_id="TechnicalModelV1",
            semantic="TECHNICAL",
            state="POSITIVE",
            score=0.8,
            confidence=0.9,
        ),
        abstain_signal(
            model_id="FundamentalModelV1",
            model_version="1",
            semantic="FUNDAMENTAL",
            instrument_id=INSTRUMENT,
            as_of=AS_OF,
            reason="unsupported",
        ),
    ]
    decision = decide(as_of=AS_OF, instrument_id=INSTRUMENT, signals=signals)
    assert decision.advisory_state == "ABSTAIN"
    assert decision.metadata["valid_model_count"] == 1
    assert "insufficient_valid_models" in decision.blockers
    assert any("at_least_2_valid" in w for w in decision.what_would_change_decision)


def test_strong_disagreement_preserved_and_lowers_confidence() -> None:
    signals = [
        _sig(
            model_id="TechnicalModelV1",
            semantic="TECHNICAL",
            state="POSITIVE",
            score=0.9,
            confidence=0.8,
        ),
        _sig(
            model_id="FundamentalModelV1",
            semantic="FUNDAMENTAL",
            state="NEGATIVE",
            score=-0.9,
            confidence=0.8,
        ),
        _sig(
            model_id="MacroModelV1",
            semantic="MACRO",
            state="POSITIVE",
            score=0.85,
            confidence=0.8,
        ),
        _sig(
            model_id="NewsModelV1",
            semantic="NEWS",
            state="NEGATIVE",
            score=-0.85,
            confidence=0.8,
        ),
    ]
    decision = decide(as_of=AS_OF, instrument_id=INSTRUMENT, signals=signals)
    assert decision.disagreement_score is not None
    assert decision.disagreement_score >= HIGH_DISAGREEMENT
    # Disagreement must not be averaged away into a strong directional call.
    assert decision.advisory_state in {"HOLD", "ABSTAIN"}
    assert decision.advisory_state != "CONSIDER_INCREASE"
    assert decision.advisory_state != "CONSIDER_REDUCE"
    # Confidence haircut vs zero-disagreement baseline.
    aligned = [
        _sig(
            model_id="TechnicalModelV1",
            semantic="TECHNICAL",
            state="POSITIVE",
            score=0.5,
            confidence=0.8,
        ),
        _sig(
            model_id="FundamentalModelV1",
            semantic="FUNDAMENTAL",
            state="POSITIVE",
            score=0.5,
            confidence=0.8,
        ),
        _sig(
            model_id="MacroModelV1",
            semantic="MACRO",
            state="POSITIVE",
            score=0.5,
            confidence=0.8,
        ),
        _sig(
            model_id="NewsModelV1",
            semantic="NEWS",
            state="POSITIVE",
            score=0.5,
            confidence=0.8,
        ),
    ]
    aligned_decision = decide(as_of=AS_OF, instrument_id=INSTRUMENT, signals=aligned)
    assert decision.confidence is not None
    assert aligned_decision.confidence is not None
    assert decision.confidence < aligned_decision.confidence
    assert len(decision.independent_model_votes) == 4
    assert any("high_disagreement" in c for c in decision.counterarguments)


def test_severe_stale_data_abstains() -> None:
    signals = [
        _sig(
            model_id="TechnicalModelV1",
            semantic="TECHNICAL",
            state="POSITIVE",
            score=0.6,
            data_freshness="STALE_SEVERE",
        ),
        _sig(
            model_id="FundamentalModelV1",
            semantic="FUNDAMENTAL",
            state="POSITIVE",
            score=0.5,
            data_freshness="FRESH",
        ),
    ]
    decision = decide(as_of=AS_OF, instrument_id=INSTRUMENT, signals=signals)
    assert decision.advisory_state == "ABSTAIN"
    assert decision.metadata["abstain_reason"] == "severe_stale_data"
    assert any("severe_stale" in b for b in decision.blockers)

    # Soft stale alone does not ABSTAIN — only haircuts confidence.
    soft = [
        _sig(
            model_id="TechnicalModelV1",
            semantic="TECHNICAL",
            state="POSITIVE",
            score=0.6,
            data_freshness="STALE",
        ),
        _sig(
            model_id="FundamentalModelV1",
            semantic="FUNDAMENTAL",
            state="POSITIVE",
            score=0.5,
            data_freshness="FRESH",
        ),
    ]
    soft_decision = decide(as_of=AS_OF, instrument_id=INSTRUMENT, signals=soft)
    assert soft_decision.advisory_state == "CONSIDER_INCREASE"
    assert "soft_stale_confidence_haircut" in soft_decision.limitations


def test_material_adverse_overrides_weak_positive() -> None:
    # Weak technical + ML positives; severe event must risk-override, not average away.
    signals = [
        _sig(
            model_id="TechnicalModelV1",
            semantic="TECHNICAL",
            state="POSITIVE",
            score=0.35,
            confidence=0.70,
        ),
        _sig(
            model_id="MLPredictionModelV1",
            semantic="ML",
            state="POSITIVE",
            score=0.32,
            confidence=0.70,
        ),
        _sig(
            model_id="EventModelV1",
            semantic="EVENT",
            state="NEGATIVE",
            score=-0.80,
            confidence=0.85,
        ),
    ]
    knowledge = [
        KnowledgeRuleEvaluation(
            rule_id="material_event_overrides_weak_trend",
            rule_version="1",
            state="TRIGGERED",
            why="material adverse event with trusted known_at",
        )
    ]
    risk = RiskAssessmentV1(
        as_of=AS_OF,
        instrument_id=INSTRUMENT,
        risk_state="ELEVATED",
        event_risk="HIGH",
        risk_flags=("material_adverse_event",),
    )
    decision = decide(
        as_of=AS_OF,
        instrument_id=INSTRUMENT,
        signals=signals,
        knowledge_evals=knowledge,
        risk=risk,
    )
    assert decision.advisory_state == "HOLD"
    assert any("material_adverse" in r for r in decision.risk_overrides)
    assert "material_event_overrides_weak_trend" in decision.triggered_knowledge_rules
    assert decision.disagreement_score is not None
    assert decision.disagreement_score > 0


def test_aligned_positive_consider_increase() -> None:
    signals = [
        _sig(
            model_id="TechnicalModelV1",
            semantic="TECHNICAL",
            state="POSITIVE",
            score=0.6,
            confidence=0.8,
        ),
        _sig(
            model_id="FundamentalModelV1",
            semantic="FUNDAMENTAL",
            state="POSITIVE",
            score=0.55,
            confidence=0.75,
        ),
    ]
    decision = decide(as_of=AS_OF, instrument_id=INSTRUMENT, signals=signals)
    assert decision.advisory_state == "CONSIDER_INCREASE"
    assert decision.disagreement_score is not None
    assert decision.disagreement_score < HIGH_DISAGREEMENT
    assert decision.confidence is not None
    assert decision.confidence > 0.4


def test_unknown_not_counted_as_valid_vote() -> None:
    from app.modules.intelligence.contracts.signal import unknown_signal

    signals = [
        _sig(
            model_id="TechnicalModelV1",
            semantic="TECHNICAL",
            state="POSITIVE",
            score=0.7,
        ),
        unknown_signal(
            model_id="FundamentalModelV1",
            model_version="1",
            semantic="FUNDAMENTAL",
            instrument_id=INSTRUMENT,
            as_of=AS_OF,
            reason="bank_industrial_ratios_unsupported",
        ),
    ]
    decision = decide(as_of=AS_OF, instrument_id=INSTRUMENT, signals=signals)
    assert decision.advisory_state == "ABSTAIN"
    assert decision.metadata["valid_model_count"] == 1


def test_determinism_same_inputs_same_output() -> None:
    signals = [
        _sig(
            model_id="TechnicalModelV1",
            semantic="TECHNICAL",
            state="NEGATIVE",
            score=-0.5,
        ),
        _sig(
            model_id="FundamentalModelV1",
            semantic="FUNDAMENTAL",
            state="NEGATIVE",
            score=-0.4,
        ),
    ]
    a = decide(as_of=AS_OF, instrument_id=INSTRUMENT, signals=signals)
    b = decide(as_of=AS_OF, instrument_id=INSTRUMENT, signals=signals)
    assert a.to_dict() == b.to_dict()
    assert a.advisory_state == "CONSIDER_REDUCE"


@pytest.mark.parametrize(
    "risk_state",
    ["HIGH"],
)
def test_high_risk_blocks_increase(risk_state: str) -> None:
    signals = [
        _sig(
            model_id="TechnicalModelV1",
            semantic="TECHNICAL",
            state="POSITIVE",
            score=0.7,
        ),
        _sig(
            model_id="FundamentalModelV1",
            semantic="FUNDAMENTAL",
            state="POSITIVE",
            score=0.65,
        ),
    ]
    risk = RiskAssessmentV1(
        as_of=AS_OF,
        instrument_id=INSTRUMENT,
        risk_state=risk_state,  # type: ignore[arg-type]
        risk_score=0.9,
    )
    decision = decide(
        as_of=AS_OF, instrument_id=INSTRUMENT, signals=signals, risk=risk
    )
    assert decision.advisory_state == "HOLD"
    assert any("risk_state_HIGH" in r for r in decision.risk_overrides)
