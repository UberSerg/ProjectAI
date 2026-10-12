"""Source adapter operations. Implementations live under sources/."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    HistoricalArtifact,
    ParsedObservation,
)


class CoverageReport:
    def __init__(
        self,
        *,
        source_id: str,
        status: AdapterStatus,
        earliest: date | None,
        latest: date | None,
        formats: tuple[str, ...],
        limitations: tuple[str, ...] = (),
    ) -> None:
        self.source_id = source_id
        self.status = status
        self.earliest = earliest
        self.latest = latest
        self.formats = formats
        self.limitations = limitations


class HistoricalSource(Protocol):
    source_id: str

    def discover(self) -> CoverageReport: ...

    def inspect_coverage(self) -> CoverageReport: ...

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]: ...

    def fetch_range(
        self, *, start: date, end: date, limit: int
    ) -> tuple[HistoricalArtifact, ...]: ...

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]: ...

    def validate(
        self, observations: tuple[ParsedObservation, ...]
    ) -> tuple[ParsedObservation, ...]: ...
