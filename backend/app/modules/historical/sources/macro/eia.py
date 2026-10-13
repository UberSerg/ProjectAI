"""INT-01 petroleum and INT-02 natural gas on the public EIA API.

Verified on 2026-10-12 without an API key. Both documented routes return
HTTP 403 and JSON error code API_KEY_MISSING. No series values are invented.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from urllib.error import URLError

from app.modules.historical.application.adapter import CoverageReport
from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    HistoricalArtifact,
    ParsedObservation,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.macro.transport import Transport, UrllibTransport

PETROLEUM_URL = (
    "https://api.eia.gov/v2/petroleum/pri/spt/data/"
    "?frequency=daily&data[0]=value&facets[series][]=RWTC"
    "&sort[0][column]=period&sort[0][direction]=desc&offset=0&length=5"
)
NATURAL_GAS_URL = (
    "https://api.eia.gov/v2/natural-gas/pri/fut/data/"
    "?frequency=daily&data[0]=value&facets[series][]=RNGWHHD"
    "&sort[0][column]=period&sort[0][direction]=desc&offset=0&length=5"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _EiaSource:
    source_id: str
    source_url: str
    document_title: str

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport if transport is not None else UrllibTransport()
        self._now = now if now is not None else _utcnow
        self.last_raw: bytes = b""
        self.last_http_status: int | None = None

    def discover(self) -> CoverageReport:
        artifact = self.fetch_sample()[0]
        blocked = self.last_http_status in {None, 0, 401, 403} or any(
            item.startswith("error_code=") for item in artifact.limitations
        )
        return CoverageReport(
            source_id=self.source_id,
            status=AdapterStatus.BLOCKED if blocked else AdapterStatus.FAILED,
            earliest=None,
            latest=None,
            formats=("json",),
            limitations=artifact.limitations,
        )

    def inspect_coverage(self) -> CoverageReport:
        return self.discover()

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        del limit
        return (self._fetch_artifact(),)

    def fetch_range(
        self, *, start: date, end: date, limit: int
    ) -> tuple[HistoricalArtifact, ...]:
        del start, end, limit
        return self.fetch_sample()

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        del artifact, raw
        return ()

    def validate(
        self, observations: tuple[ParsedObservation, ...]
    ) -> tuple[ParsedObservation, ...]:
        return observations

    def _fetch_artifact(self) -> HistoricalArtifact:
        fetched_at = self._now()
        try:
            result_status, body = self._request()
        except URLError as exc:
            body = str(exc.reason).encode("utf-8", errors="replace")
            result_status = 0
        self.last_http_status = result_status
        self.last_raw = body
        limitations = [f"http_status={result_status}", "api_key_not_sent"]
        error_code = _error_code(body)
        if error_code is not None:
            limitations.append(f"error_code={error_code}")
        fetch_status = FetchStatus.FORBIDDEN if result_status in {401, 403} else FetchStatus.FAILED
        return HistoricalArtifact(
            source_id=self.source_id,
            source_url=self.source_url,
            external_document_id=f"{self.source_id.lower()}-api-v2",
            document_type="macro_series",
            content_hash=hashlib.sha256(body).hexdigest(),
            parser_version="eia_api_v2_blocked",
            fetch_status=fetch_status,
            first_observed_at=fetched_at,
            title=self.document_title,
            entity_identifiers={"http_status": str(result_status)},
            published_at_precision=PublishedAtPrecision.UNKNOWN,
            historical_pit_quality=PitQuality.RESEARCH_ONLY,
            quality_status=RecordQuality.UNRESOLVED,
            limitations=tuple(limitations),
        )

    def _request(self) -> tuple[int, bytes]:
        result = self._transport.request(self.source_url)
        return result.status, result.body


class EiaPetroleumSource(_EiaSource):
    source_id = "INT-01"
    source_url = PETROLEUM_URL
    document_title = "EIA petroleum spot prices (WTI, series RWTC)"


class EiaNaturalGasSource(_EiaSource):
    source_id = "INT-02"
    source_url = NATURAL_GAS_URL
    document_title = "EIA Henry Hub natural gas spot price (series RNGWHHD)"


def _error_code(body: bytes) -> str | None:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    if isinstance(code, str) and code:
        return code
    return None
