"""Shared historical evidence contract.

This is not a second market stack. Adapters emit these records.
Raw bytes stay outside git. Nothing here writes prospective captures,
signals, committee decisions, or broker orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class PitQuality(StrEnum):
    PIT_VERIFIED = "PIT_VERIFIED"
    PIT_PROXY = "PIT_PROXY"
    RESEARCH_ONLY = "RESEARCH_ONLY"


class PublishedAtPrecision(StrEnum):
    TIMESTAMP = "TIMESTAMP"
    DATE_ONLY = "DATE_ONLY"
    PERIOD_ONLY = "PERIOD_ONLY"
    UNKNOWN = "UNKNOWN"


class FetchStatus(StrEnum):
    OK = "OK"
    EMPTY = "EMPTY"
    RATE_LIMITED = "RATE_LIMITED"
    FORBIDDEN = "FORBIDDEN"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


class RecordQuality(StrEnum):
    ACCEPTED = "ACCEPTED"
    QUARANTINE = "QUARANTINE"
    UNRESOLVED = "UNRESOLVED"


class AdapterStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class HistoricalArtifact:
    source_id: str
    source_url: str
    external_document_id: str
    document_type: str
    content_hash: str
    parser_version: str
    fetch_status: FetchStatus
    first_observed_at: datetime
    title: str | None = None
    entity_identifiers: dict[str, str] = field(default_factory=dict)
    reporting_period: str | None = None
    period_end: date | None = None
    event_date: date | None = None
    published_at: datetime | None = None
    published_at_precision: PublishedAtPrecision = PublishedAtPrecision.UNKNOWN
    historical_availability_evidence: str | None = None
    historical_pit_quality: PitQuality = PitQuality.RESEARCH_ONLY
    revision_identifier: str | None = None
    raw_artifact_reference: str | None = None
    quality_status: RecordQuality = RecordQuality.UNRESOLVED
    limitations: tuple[str, ...] = ()

    def chronology_errors(self) -> tuple[str, ...]:
        # period_end and known_at / published_at / first_observed_at stay different
        # fields. Equal calendar dates are valid and are not a chronology error.
        errors: list[str] = []
        if self.published_at is not None and self.first_observed_at < self.published_at:
            errors.append("first_observed_at_precedes_published_at")
        if self.historical_pit_quality == PitQuality.PIT_VERIFIED and (
            self.published_at is None or self.historical_availability_evidence is None
        ):
            errors.append("pit_verified_requires_publication_evidence")
        return tuple(errors)


@dataclass(frozen=True, slots=True)
class ParsedObservation:
    metric_id: str
    source_id: str
    content_hash: str
    normalization_version: str
    quality_status: RecordQuality
    value: float | None = None
    unit: str | None = None
    currency: str | None = None
    period: str | None = None
    period_end: date | None = None
    reporting_standard: str | None = None
    issuer_identity: dict[str, str] = field(default_factory=dict)
    evidence: str | None = None
    limitations: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    def quality_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.quality_status == RecordQuality.ACCEPTED and not self.evidence:
            errors.append("accepted_fact_requires_evidence")
        if self.value == 0 and "explicit_zero" not in self.limitations:
            errors.append("zero_requires_explicit_zero_mark")
        if self.quality_status == RecordQuality.ACCEPTED and not self.issuer_identity and (
            self.metric_id.startswith("issuer.")
        ):
            errors.append("issuer_fact_requires_identity")
        return tuple(errors)
