"""KnowledgeRule + evaluation contracts (rules never issue trades)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RuleEvalState = Literal["TRIGGERED", "VIOLATED", "NOT_APPLICABLE", "UNKNOWN"]
RULE_EVAL_STATES: frozenset[str] = frozenset(
    {"TRIGGERED", "VIOLATED", "NOT_APPLICABLE", "UNKNOWN"}
)


@dataclass(frozen=True, slots=True)
class KnowledgeRule:
    rule_id: str
    version: str
    domain: str
    title: str
    principle: str
    applicability: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    contraindications: tuple[str, ...] = ()
    severity: str = "MEDIUM"
    source_reference: str | None = None
    source_location: str | None = None
    created_from: str = "kraken_methodology"
    status: str = "ACTIVE"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["applicability"] = list(self.applicability)
        payload["required_evidence"] = list(self.required_evidence)
        payload["contraindications"] = list(self.contraindications)
        return payload


@dataclass(frozen=True, slots=True)
class KnowledgeRuleEvaluation:
    rule_id: str
    rule_version: str
    state: RuleEvalState
    why: str
    evidence_refs: tuple[dict[str, Any], ...] = ()
    instrument_id: int | None = None
    as_of: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in RULE_EVAL_STATES:
            raise ValueError(f"invalid rule eval state: {self.state!r}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload
