"""IntelligenceSnapshotV1 — aggregate OWNER company intelligence payload."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from app.modules.intelligence.contracts.committee import CommitteeDecisionV1
from app.modules.intelligence.contracts.risk import RiskAssessmentV1
from app.modules.intelligence.contracts.signal import SignalOutputV1


@dataclass(frozen=True, slots=True)
class CoverageItem:
    domain: str
    status: str  # READY | PARTIAL | NOT_READY | UNKNOWN
    detail: str | None = None
    last_known_at: date | datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        value = payload.get("last_known_at")
        if isinstance(value, date | datetime):
            payload["last_known_at"] = value.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class IntelligenceSnapshotV1:
    schema: str = "IntelligenceSnapshotV1"
    instrument_id: int = 0
    symbol: str | None = None
    name: str | None = None
    as_of: date | None = None
    generated_at: datetime | None = None
    freshness: str | None = None
    coverage: tuple[CoverageItem, ...] = ()
    signals: tuple[SignalOutputV1, ...] = ()
    committee: CommitteeDecisionV1 | None = None
    risk: RiskAssessmentV1 | None = None
    fundamentals_summary: dict[str, Any] = field(default_factory=dict)
    macro_summary: dict[str, Any] = field(default_factory=dict)
    recent_events: tuple[dict[str, Any], ...] = ()
    knowledge_evaluations: tuple[dict[str, Any], ...] = ()
    intraday_summary: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    production_isolation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "name": self.name,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "freshness": self.freshness,
            "coverage": [c.to_dict() for c in self.coverage],
            "signals": [s.to_dict() for s in self.signals],
            "committee": self.committee.to_dict() if self.committee else None,
            "risk": self.risk.to_dict() if self.risk else None,
            "fundamentals_summary": dict(self.fundamentals_summary),
            "macro_summary": dict(self.macro_summary),
            "recent_events": list(self.recent_events),
            "knowledge_evaluations": list(self.knowledge_evaluations),
            "intraday_summary": dict(self.intraday_summary),
            "limitations": list(self.limitations),
            "production_isolation": dict(self.production_isolation),
        }
