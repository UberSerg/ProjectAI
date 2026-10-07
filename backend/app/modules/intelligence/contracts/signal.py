"""SignalOutputV1 — canonical independent analytical model output."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from app.modules.intelligence.contracts.provenance import EvidenceRef

SignalState = Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "ABSTAIN", "UNKNOWN"]
SIGNAL_STATES: frozenset[str] = frozenset(
    {"POSITIVE", "NEUTRAL", "NEGATIVE", "ABSTAIN", "UNKNOWN"}
)

# Confidence is NOT probability of profit. It measures evidence completeness /
# stability / agreement per documented model semantics.
ConfidenceSemantic = Literal[
    "EVIDENCE_COMPLETENESS",
    "STABILITY",
    "AGREEMENT",
    "MODEL_DEFINED",
    "UNSPECIFIED",
]


@dataclass(frozen=True, slots=True)
class SignalOutputV1:
    model_id: str
    model_version: str
    semantic: str
    instrument_id: int
    as_of: date
    known_at: date | datetime | None
    horizon: str
    state: SignalState
    score: float | None = None
    confidence: float | None = None
    confidence_semantic: ConfidenceSemantic = "UNSPECIFIED"
    evidence_refs: tuple[EvidenceRef, ...] = ()
    feature_snapshot_hash: str | None = None
    data_freshness: str | None = None
    limitations: tuple[str, ...] = ()
    abstain_reason: str | None = None
    model_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in SIGNAL_STATES:
            raise ValueError(f"invalid SignalOutputV1.state: {self.state!r}")
        if self.score is not None and not (-1.0 <= float(self.score) <= 1.0):
            raise ValueError("SignalOutputV1.score must be in [-1, 1] when set")
        if self.confidence is not None and not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError("SignalOutputV1.confidence must be in [0, 1] when set")
        # Models never emit orders/actions.
        forbidden = {"order", "orders", "broker", "execution", "trade_intent"}
        bad = forbidden.intersection(self.model_metadata)
        if bad:
            raise ValueError(f"SignalOutputV1.model_metadata forbids keys: {sorted(bad)}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        if isinstance(self.known_at, datetime):
            payload["known_at"] = self.known_at.isoformat()
        elif isinstance(self.known_at, date):
            payload["known_at"] = self.known_at.isoformat()
        payload["evidence_refs"] = [ref.to_dict() for ref in self.evidence_refs]
        payload["limitations"] = list(self.limitations)
        return payload


def abstain_signal(
    *,
    model_id: str,
    model_version: str,
    semantic: str,
    instrument_id: int,
    as_of: date,
    reason: str,
    horizon: str = "unspecified",
    limitations: tuple[str, ...] = (),
) -> SignalOutputV1:
    return SignalOutputV1(
        model_id=model_id,
        model_version=model_version,
        semantic=semantic,
        instrument_id=instrument_id,
        as_of=as_of,
        known_at=None,
        horizon=horizon,
        state="ABSTAIN",
        score=None,
        confidence=None,
        abstain_reason=reason,
        limitations=limitations,
    )


def unknown_signal(
    *,
    model_id: str,
    model_version: str,
    semantic: str,
    instrument_id: int,
    as_of: date,
    reason: str,
    horizon: str = "unspecified",
) -> SignalOutputV1:
    return SignalOutputV1(
        model_id=model_id,
        model_version=model_version,
        semantic=semantic,
        instrument_id=instrument_id,
        as_of=as_of,
        known_at=None,
        horizon=horizon,
        state="UNKNOWN",
        score=None,
        confidence=None,
        abstain_reason=reason,
        limitations=(reason,),
    )
