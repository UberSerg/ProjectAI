"""Universal time / provenance contracts for external intelligence artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ProvenanceTimestamps:
    """Distinguish publication, observation, and decision-availability."""

    source_published_at: datetime | date | None = None
    observed_at: datetime | date | None = None
    known_at: datetime | date | None = None
    effective_at: datetime | date | None = None
    period_end: date | None = None
    ingested_at: datetime | date | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in asdict(self).items():
            if value is None:
                out[key] = None
            elif isinstance(value, datetime):
                out[key] = value.isoformat()
            elif isinstance(value, date):
                out[key] = value.isoformat()
            else:
                out[key] = value
        return out


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Pointer to immutable/append-only source material."""

    source_type: str
    provider: str
    canonical_url: str | None = None
    source_document_id: str | None = None
    content_hash: str | None = None
    published_at: datetime | date | None = None
    observed_at: datetime | date | None = None
    known_at: datetime | date | None = None
    issuer_mapping_basis: str | None = None
    parser_version: str | None = None
    note: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("published_at", "observed_at", "known_at"):
            value = payload.get(key)
            if isinstance(value, datetime | date):
                payload[key] = value.isoformat()
        return payload


def known_at_allows(as_of: date | datetime, known_at: date | datetime | None) -> bool:
    """Point-in-time gate: item is usable iff known_at is set and <= as_of."""
    if known_at is None:
        return False
    as_of_d = as_of.date() if isinstance(as_of, datetime) else as_of
    known_d = known_at.date() if isinstance(known_at, datetime) else known_at
    return known_d <= as_of_d
