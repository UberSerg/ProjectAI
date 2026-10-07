"""Structured LLM extraction contracts — facts with evidence, not numerical truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

EXTRACTOR_VERSION = "intelligence_extractor_v1"

EventType = Literal[
    "EARNINGS",
    "GUIDANCE",
    "DIVIDEND",
    "CAPEX",
    "M&A",
    "BUYBACK",
    "SPO",
    "DEBT",
    "SANCTIONS",
    "REGULATORY",
    "MANAGEMENT",
    "OPERATIONAL_INCIDENT",
    "PRODUCTION",
    "CONTRACT",
    "LITIGATION",
    "CREDIT_RATING",
    "OTHER",
]

EVENT_TYPES: frozenset[str] = frozenset(
    {
        "EARNINGS",
        "GUIDANCE",
        "DIVIDEND",
        "CAPEX",
        "M&A",
        "BUYBACK",
        "SPO",
        "DEBT",
        "SANCTIONS",
        "REGULATORY",
        "MANAGEMENT",
        "OPERATIONAL_INCIDENT",
        "PRODUCTION",
        "CONTRACT",
        "LITIGATION",
        "CREDIT_RATING",
        "OTHER",
    }
)

Materiality = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
MATERIALITY_VALUES: frozenset[str] = frozenset({"LOW", "MEDIUM", "HIGH", "UNKNOWN"})

Direction = Literal["POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"]
DIRECTION_VALUES: frozenset[str] = frozenset(
    {"POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"}
)

ExtractionStatus = Literal[
    "OK",
    "LLM_UNAVAILABLE",
    "REJECTED",
    "UNKNOWN",
    "EMPTY",
]
EXTRACTION_STATUSES: frozenset[str] = frozenset(
    {"OK", "LLM_UNAVAILABLE", "REJECTED", "UNKNOWN", "EMPTY"}
)

# Forbidden as trading actions / instruction obedience — not SignalOutput states.
FORBIDDEN_ACTION_TOKENS: frozenset[str] = frozenset(
    {
        "BUY",
        "SELL",
        "HOLD",
        "INCREASE",
        "REDUCE",
        "EXECUTE",
        "ORDER",
        "TRADE",
        "LONG",
        "SHORT",
    }
)

# Never persist these keys from provider payloads (hidden chain-of-thought).
FORBIDDEN_PERSISTENCE_KEYS: frozenset[str] = frozenset(
    {
        "chain_of_thought",
        "chainOfThought",
        "reasoning_trace",
        "reasoningTrace",
        "thinking",
        "private_reasoning",
        "scratchpad",
        "cot",
        "hidden_rationale",
    }
)


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


@dataclass(frozen=True, slots=True)
class NumericalFactV1:
    """Numerical claim retained with units and evidence — not treated as truth alone."""

    value: float | None
    unit: str | None = None
    currency: str | None = None
    period: str | None = None
    effective_date: date | None = None
    evidence_fragment: str | None = None
    status: str = "OK"  # OK | UNKNOWN | REJECTED

    def __post_init__(self) -> None:
        if self.status not in {"OK", "UNKNOWN", "REJECTED"}:
            raise ValueError(f"invalid NumericalFactV1.status: {self.status!r}")
        if self.status == "OK" and self.value is None:
            raise ValueError("NumericalFactV1 with status OK requires value")
        if self.status == "OK" and not (self.evidence_fragment or "").strip():
            raise ValueError("NumericalFactV1 with status OK requires evidence_fragment")

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "currency": self.currency,
            "period": self.period,
            "effective_date": _iso(self.effective_date),
            "evidence_fragment": self.evidence_fragment,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ExtractedClaimV1:
    """One structured factual claim grounded in a source document."""

    claim_id: str
    text: str
    source_document_id: str
    evidence_fragment: str
    extractor_version: str
    confidence: float
    numerical: NumericalFactV1 | None = None
    claim_type: str = "FACTUAL"

    def __post_init__(self) -> None:
        if not self.source_document_id.strip():
            raise ValueError("ExtractedClaimV1.source_document_id is required")
        if not self.evidence_fragment.strip():
            raise ValueError("ExtractedClaimV1.evidence_fragment is required")
        if not self.extractor_version.strip():
            raise ValueError("ExtractedClaimV1.extractor_version is required")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError("ExtractedClaimV1.confidence must be in [0, 1]")
        if self.claim_type == "ACTION":
            raise ValueError("ExtractedClaimV1 forbids ACTION claims")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "source_document_id": self.source_document_id,
            "evidence_fragment": self.evidence_fragment,
            "extractor_version": self.extractor_version,
            "confidence": self.confidence,
            "numerical": self.numerical.to_dict() if self.numerical else None,
            "claim_type": self.claim_type,
        }


@dataclass(frozen=True, slots=True)
class ExtractedEventV1:
    """Structured event extraction — advisory research only, never an order."""

    event_type: EventType
    materiality: Materiality
    direction: Direction
    affected_horizon: str
    claims: tuple[ExtractedClaimV1, ...]
    rationale: str = ""
    confidence: float | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"invalid event_type: {self.event_type!r}")
        if self.materiality not in MATERIALITY_VALUES:
            raise ValueError(f"invalid materiality: {self.materiality!r}")
        if self.direction not in DIRECTION_VALUES:
            raise ValueError(f"invalid direction: {self.direction!r}")
        if self.direction.upper() in FORBIDDEN_ACTION_TOKENS:
            raise ValueError(f"direction must not be a trading action: {self.direction!r}")
        if self.confidence is not None and not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError("ExtractedEventV1.confidence must be in [0, 1] when set")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "materiality": self.materiality,
            "direction": self.direction,
            "affected_horizon": self.affected_horizon,
            "claims": [c.to_dict() for c in self.claims],
            "rationale": self.rationale,
            "confidence": self.confidence,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class ExtractionResultV1:
    """Runtime result of IntelligenceExtractor — may be LLM_UNAVAILABLE."""

    status: ExtractionStatus
    source_document_id: str
    extractor_version: str
    provider_name: str
    events: tuple[ExtractedEventV1, ...] = ()
    limitations: tuple[str, ...] = ()
    content_trust: str = "UNTRUSTED"
    # Concise evidence-based note only — never chain-of-thought.
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in EXTRACTION_STATUSES:
            raise ValueError(f"invalid ExtractionResultV1.status: {self.status!r}")
        if self.content_trust != "UNTRUSTED":
            raise ValueError("source content must be marked UNTRUSTED")
        bad = FORBIDDEN_PERSISTENCE_KEYS.intersection(self.metadata)
        if bad:
            raise ValueError(
                f"ExtractionResultV1.metadata forbids chain-of-thought keys: {sorted(bad)}"
            )
        if self.status == "LLM_UNAVAILABLE" and self.events:
            raise ValueError("LLM_UNAVAILABLE must not carry extracted events")
        if self.status == "OK" and not self.events:
            raise ValueError("OK extraction requires at least one event (use EMPTY)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ExtractionResultV1",
            "status": self.status,
            "source_document_id": self.source_document_id,
            "extractor_version": self.extractor_version,
            "provider_name": self.provider_name,
            "events": [e.to_dict() for e in self.events],
            "limitations": list(self.limitations),
            "content_trust": self.content_trust,
            "summary": self.summary,
            "metadata": dict(self.metadata),
        }

    def persistable_dict(self) -> dict[str, Any]:
        """Only structured factual output safe to store — no hidden reasoning."""
        payload = self.to_dict()
        # Defensive strip if any nested forbidden keys slipped into metadata.
        meta = {
            k: v
            for k, v in payload["metadata"].items()
            if k not in FORBIDDEN_PERSISTENCE_KEYS
        }
        payload["metadata"] = meta
        return payload


def unavailable_result(
    *,
    source_document_id: str,
    provider_name: str = "none",
    reason: str = "no_llm_provider_configured",
) -> ExtractionResultV1:
    return ExtractionResultV1(
        status="LLM_UNAVAILABLE",
        source_document_id=source_document_id,
        extractor_version=EXTRACTOR_VERSION,
        provider_name=provider_name,
        events=(),
        limitations=(reason, "do_not_fabricate_facts"),
        summary=None,
        metadata={"fabricated": False},
    )
