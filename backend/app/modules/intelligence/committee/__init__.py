"""Investment Committee — deterministic multi-model advisory combination."""

from collections.abc import Sequence
from datetime import date

from app.modules.intelligence.committee.decide import decide, decide_many
from app.modules.intelligence.committee.policy_v1 import (
    MIN_VALID_MODELS,
    POLICY_VERSION,
    SEMANTIC_WEIGHTS,
)
from app.modules.intelligence.contracts.committee import (
    COMMITTEE_POLICY_VERSION,
    CommitteeDecisionV1,
)
from app.modules.intelligence.contracts.knowledge import KnowledgeRuleEvaluation
from app.modules.intelligence.contracts.risk import RiskAssessmentV1
from app.modules.intelligence.contracts.signal import SignalOutputV1


def decide_committee(
    *,
    instrument_id: int,
    as_of: date,
    signals: Sequence[SignalOutputV1],
    knowledge_evals: Sequence[KnowledgeRuleEvaluation] = (),
    risk: RiskAssessmentV1 | None = None,
) -> CommitteeDecisionV1:
    return decide(
        as_of=as_of,
        instrument_id=instrument_id,
        signals=signals,
        knowledge_evals=knowledge_evals,
        risk=risk,
    )


__all__ = [
    "COMMITTEE_POLICY_VERSION",
    "CommitteeDecisionV1",
    "MIN_VALID_MODELS",
    "POLICY_VERSION",
    "SEMANTIC_WEIGHTS",
    "decide",
    "decide_committee",
    "decide_many",
]