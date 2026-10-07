"""CommitteeDecisionV1 — deterministic multi-model advisory combination."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

from app.modules.intelligence.contracts.provenance import EvidenceRef
from app.modules.intelligence.contracts.signal import SignalOutputV1

AdvisoryState = Literal["CONSIDER_INCREASE", "HOLD", "CONSIDER_REDUCE", "ABSTAIN"]
ADVISORY_STATES: frozenset[str] = frozenset(
    {"CONSIDER_INCREASE", "HOLD", "CONSIDER_REDUCE", "ABSTAIN"}
)

COMMITTEE_POLICY_VERSION = "committee_policy_v1_predeclared"


@dataclass(frozen=True, slots=True)
class ModelVote:
    model_id: str
    state: str
    score: float | None
    confidence: float | None
    weight_applied: float | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CommitteeDecisionV1:
    as_of: date
    instrument_id: int
    advisory_state: AdvisoryState
    confidence: float | None
    consensus_strength: float | None
    disagreement_score: float | None
    independent_model_votes: tuple[ModelVote, ...]
    primary_drivers: tuple[str, ...] = ()
    counterarguments: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    data_gaps: tuple[str, ...] = ()
    triggered_knowledge_rules: tuple[str, ...] = ()
    risk_overrides: tuple[str, ...] = ()
    what_would_change_decision: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    committee_policy_version: str = COMMITTEE_POLICY_VERSION
    limitations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.advisory_state not in ADVISORY_STATES:
            raise ValueError(f"invalid advisory_state: {self.advisory_state!r}")
        for name, value in (
            ("confidence", self.confidence),
            ("consensus_strength", self.consensus_strength),
            ("disagreement_score", self.disagreement_score),
        ):
            if value is not None and not (0.0 <= float(value) <= 1.0):
                raise ValueError(f"{name} must be in [0, 1] when set")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        payload["independent_model_votes"] = [v.to_dict() for v in self.independent_model_votes]
        payload["evidence_refs"] = [r.to_dict() for r in self.evidence_refs]
        for key in (
            "primary_drivers",
            "counterarguments",
            "blockers",
            "data_gaps",
            "triggered_knowledge_rules",
            "risk_overrides",
            "what_would_change_decision",
            "limitations",
        ):
            payload[key] = list(getattr(self, key))
        return payload


def votes_from_signals(signals: list[SignalOutputV1]) -> tuple[ModelVote, ...]:
    return tuple(
        ModelVote(
            model_id=s.model_id,
            state=s.state,
            score=s.score,
            confidence=s.confidence,
        )
        for s in signals
    )
