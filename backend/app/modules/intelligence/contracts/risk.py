"""RiskAssessmentV1 — risk is not prediction."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

from app.modules.intelligence.contracts.provenance import EvidenceRef

RiskState = Literal["LOW", "MODERATE", "ELEVATED", "HIGH", "UNKNOWN"]
RISK_STATES: frozenset[str] = frozenset({"LOW", "MODERATE", "ELEVATED", "HIGH", "UNKNOWN"})


@dataclass(frozen=True, slots=True)
class ScenarioImpact:
    """Deterministic stress scenario — not a probability forecast."""

    scenario_id: str
    description: str
    price_shock: float | None = None
    nav_impact: float | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True, slots=True)
class RiskAssessmentV1:
    as_of: date
    instrument_id: int
    risk_state: RiskState
    risk_score: float | None = None
    risk_flags: tuple[str, ...] = ()
    liquidity_state: str | None = None
    volatility_state: str | None = None
    event_risk: str | None = None
    data_risk: str | None = None
    concentration_risk: str | None = None
    scenarios: tuple[ScenarioImpact, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.risk_state not in RISK_STATES:
            raise ValueError(f"invalid risk_state: {self.risk_state!r}")
        if self.risk_score is not None and not (0.0 <= float(self.risk_score) <= 1.0):
            raise ValueError("risk_score must be in [0, 1] when set")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        payload["risk_flags"] = list(self.risk_flags)
        payload["limitations"] = list(self.limitations)
        payload["scenarios"] = [s.to_dict() for s in self.scenarios]
        payload["evidence_refs"] = [r.to_dict() for r in self.evidence_refs]
        return payload
