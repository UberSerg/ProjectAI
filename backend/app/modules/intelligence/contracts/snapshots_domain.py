"""Domain snapshot contracts (fundamentals / intraday / macro) — JSON-friendly dicts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


@dataclass(frozen=True, slots=True)
class FundamentalSnapshotV1:
    schema: str = "FundamentalSnapshotV1"
    instrument_id: int = 0
    as_of: date | None = None
    known_at: date | datetime | None = None
    period_end: date | None = None
    issuer_kind: str = "INDUSTRIAL"  # INDUSTRIAL | BANK_FI | UNKNOWN
    status: str = "PARTIAL"  # READY | PARTIAL | NOT_AVAILABLE | UNKNOWN
    metrics: dict[str, Any] = field(default_factory=dict)
    missing_metrics: tuple[str, ...] = ()
    facts_used: tuple[dict[str, Any], ...] = ()
    limitations: tuple[str, ...] = ()
    provider: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "instrument_id": self.instrument_id,
            "as_of": _iso(self.as_of),
            "known_at": _iso(self.known_at),
            "period_end": _iso(self.period_end),
            "issuer_kind": self.issuer_kind,
            "status": self.status,
            "metrics": dict(self.metrics),
            "missing_metrics": list(self.missing_metrics),
            "facts_used": list(self.facts_used),
            "limitations": list(self.limitations),
            "provider": self.provider,
        }


@dataclass(frozen=True, slots=True)
class IntradayFeatureSnapshotV1:
    schema: str = "IntradayFeatureSnapshotV1"
    instrument_id: int = 0
    as_of: date | None = None
    known_at: date | datetime | None = None
    interval: str = "60m"
    coverage_status: str = "UNKNOWN"
    features: dict[str, float | None] = field(default_factory=dict)
    bars_used: int = 0
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "instrument_id": self.instrument_id,
            "as_of": _iso(self.as_of),
            "known_at": _iso(self.known_at),
            "interval": self.interval,
            "coverage_status": self.coverage_status,
            "features": dict(self.features),
            "bars_used": self.bars_used,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class MacroSnapshotV1:
    schema: str = "MacroSnapshotV1"
    as_of: date | None = None
    known_at: date | datetime | None = None
    status: str = "PARTIAL"
    observations: dict[str, Any] = field(default_factory=dict)
    regimes: dict[str, str] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "as_of": _iso(self.as_of),
            "known_at": _iso(self.known_at),
            "status": self.status,
            "observations": dict(self.observations),
            "regimes": dict(self.regimes),
            "limitations": list(self.limitations),
            "sources": list(self.sources),
        }


@dataclass(frozen=True, slots=True)
class SourceDocumentV1:
    """Logical document contract (persistence may map to intelligence.source_documents)."""

    id: str
    provider: str
    source_type: str
    canonical_url: str | None
    title: str | None
    published_at: datetime | date | None
    observed_at: datetime | date | None
    known_at: datetime | date | None
    content_hash: str
    language: str | None = None
    issuer_id: int | None = None
    instrument_id: int | None = None
    mapping_basis: str | None = None
    parse_status: str = "PENDING"
    raw_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("published_at", "observed_at", "known_at"):
            value = payload.get(key)
            if isinstance(value, date | datetime):
                payload[key] = value.isoformat()
        return payload
