"""ROS-01: Rosstat CPI via the official EMISS JSON grid.

Verified on 2026-10-12: POST
https://www.fedstat.ru/indicator/dataGrid.do?id=31074
returns HTTP 200 JSON for the national month-on-month CPI
(«Все товары и услуги», «К предыдущему месяцу») for 2017-2022.
The same filters for 2023-2026 return HTTP 200 and zero rows.
SDMX download at downloadData.do answers HTTP 200 with an HTML CSRF block.
rosstat.gov.ru files were not read: TLS certificate verification failed
(issuer Russian Trusted Sub CA).
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
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
from app.modules.historical.sources.macro.transport import HttpResult, Transport, UrllibTransport

SOURCE_ID = "ROS-01"
SOURCE_URL = "https://www.fedstat.ru/indicator/dataGrid.do?id=31074"
PARSER_VERSION = "rosstat_cpi_emiss_v1"
MAX_OBSERVATIONS = 120
INDICATOR_ID = "31074"
TERRITORY_ID = "1688487"
TERRITORY_NAME = "Российская Федерация"
GOODS_ID = "1707675"
GOODS_NAME = "Все товары и услуги"
MEASURE_ID = "1704142"
UNIT_ID = "950473"

# EMISS period ids for calendar months. Quarter ids are intentionally absent.
MONTH_PERIOD_IDS: dict[int, int] = {
    1540283: 1,
    1540282: 2,
    1540236: 3,
    1540229: 4,
    1540235: 5,
    1540234: 6,
    1540233: 7,
    1540228: 8,
    1540276: 9,
    1540273: 10,
    1540272: 11,
    1540230: 12,
}

_CELL = re.compile(r"^dim(\d{4})_(\d+)_(\d+)_d\d+_i\d+$")

_PROBE_LIMITATIONS = (
    "sdmx_download_http_200_csrf_block",
    "rosstat_gov_ru_tls_certificate_verify_failed",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RosstatCpiSource:
    source_id = SOURCE_ID

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
        artifact = self.fetch_sample(limit=MAX_OBSERVATIONS)[0]
        observations = self.parse(artifact, self.last_raw)
        earliest = observations[0].period_end if observations else None
        latest = observations[-1].period_end if observations else None
        return CoverageReport(
            source_id=self.source_id,
            status=self._adapter_status(observations),
            earliest=earliest,
            latest=latest,
            formats=("json",),
            limitations=artifact.limitations,
        )

    def inspect_coverage(self) -> CoverageReport:
        return self.discover()

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        return (self._load_artifact(limit=_cap(limit), start=None, end=None),)

    def fetch_range(
        self, *, start: date, end: date, limit: int
    ) -> tuple[HistoricalArtifact, ...]:
        return (self._load_artifact(limit=_cap(limit), start=start, end=end),)

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if artifact.fetch_status is not FetchStatus.OK:
            return ()
        payload = _load_json(raw)
        if payload is None:
            return ()
        observations: list[ParsedObservation] = []
        for row in payload.get("results") or []:
            if not isinstance(row, dict):
                continue
            if row.get("dim57831") not in (None, TERRITORY_NAME):
                continue
            if row.get("dim58273") not in (None, GOODS_NAME):
                continue
            observations.extend(self._row_observations(artifact, row))
        observations.sort(key=lambda item: item.period_end or date.min)
        start = _parse_date(artifact.entity_identifiers.get("range_start"))
        end = _parse_date(artifact.entity_identifiers.get("range_end"))
        ranged = [item for item in observations if _in_range(item.period_end, start, end)]
        limit = _cap(int(artifact.entity_identifiers.get("observation_limit") or MAX_OBSERVATIONS))
        return tuple(ranged[-limit:])

    def validate(
        self, observations: tuple[ParsedObservation, ...]
    ) -> tuple[ParsedObservation, ...]:
        checked: list[ParsedObservation] = []
        for observation in observations:
            if observation.quality_errors() and observation.quality_status is RecordQuality.ACCEPTED:
                checked.append(
                    ParsedObservation(
                        metric_id=observation.metric_id,
                        source_id=observation.source_id,
                        content_hash=observation.content_hash,
                        normalization_version=observation.normalization_version,
                        quality_status=RecordQuality.QUARANTINE,
                        value=observation.value,
                        unit=observation.unit,
                        currency=observation.currency,
                        period=observation.period,
                        period_end=observation.period_end,
                        reporting_standard=observation.reporting_standard,
                        issuer_identity=observation.issuer_identity,
                        evidence=observation.evidence,
                        limitations=observation.limitations,
                        extra=observation.extra,
                    )
                )
            else:
                checked.append(observation)
        return tuple(checked)

    def _load_artifact(
        self, *, limit: int, start: date | None, end: date | None
    ) -> HistoricalArtifact:
        result = self._fetch()
        return self._artifact(result.body, result.status, self._now(), limit=limit, start=start, end=end)

    def _fetch(self) -> HttpResult:
        try:
            result = self._transport.request(
                SOURCE_URL,
                data=self._query_body(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except URLError as exc:
            body = str(exc.reason).encode("utf-8", errors="replace")
            self.last_http_status = 0
            self.last_raw = body
            return HttpResult(url=SOURCE_URL, status=0, body=body)
        self.last_http_status = result.status
        self.last_raw = result.body
        return result

    def _query_body(self) -> bytes:
        end_year = self._now().year
        start_year = end_year - 9
        parts = [
            "lineObjectIds=57831",
            "lineObjectIds=58273",
            "lineObjectIds=30611",
            "columnObjectIds=3",
            "columnObjectIds=33560",
            "columnObjectIds=57937",
            "selectedFilterIds=0_31074",
            f"selectedFilterIds=57831_{TERRITORY_ID}",
            f"selectedFilterIds=58273_{GOODS_ID}",
            f"selectedFilterIds=57937_{MEASURE_ID}",
            f"selectedFilterIds=30611_{UNIT_ID}",
        ]
        parts.extend(f"selectedFilterIds=3_{year}" for year in range(start_year, end_year + 1))
        parts.extend(f"selectedFilterIds=33560_{period_id}" for period_id in MONTH_PERIOD_IDS)
        return "&".join(parts).encode("ascii")

    def _artifact(
        self,
        raw: bytes,
        http_status: int,
        fetched_at: datetime,
        *,
        limit: int,
        start: date | None,
        end: date | None,
    ) -> HistoricalArtifact:
        payload = _load_json(raw) if http_status == 200 else None
        parsed_count = _count_cells(payload) if payload is not None else 0
        fetch_status = _fetch_status(http_status, parsed_count)
        limitations = [_http_limitation(http_status), *_PROBE_LIMITATIONS]
        if http_status == 200 and parsed_count == 0:
            limitations.append("national_cpi_slice_empty")
        identifiers = {
            "indicator_id": INDICATOR_ID,
            "territory_id": TERRITORY_ID,
            "goods_id": GOODS_ID,
            "measure_id": MEASURE_ID,
            "http_status": str(http_status),
            "observation_limit": str(limit),
        }
        if start is not None:
            identifiers["range_start"] = start.isoformat()
        if end is not None:
            identifiers["range_end"] = end.isoformat()
        return HistoricalArtifact(
            source_id=self.source_id,
            source_url=SOURCE_URL,
            external_document_id=f"fedstat-{INDICATOR_ID}-cpi-mom-rf",
            document_type="macro_series",
            content_hash=hashlib.sha256(raw).hexdigest(),
            parser_version=PARSER_VERSION,
            fetch_status=fetch_status,
            first_observed_at=fetched_at,
            title="Индексы потребительских цен на товары и услуги",
            entity_identifiers=identifiers,
            published_at_precision=PublishedAtPrecision.UNKNOWN,
            historical_pit_quality=PitQuality.RESEARCH_ONLY,
            quality_status=(
                RecordQuality.ACCEPTED if fetch_status is FetchStatus.OK else RecordQuality.UNRESOLVED
            ),
            limitations=tuple(limitations),
        )

    def _adapter_status(self, observations: tuple[ParsedObservation, ...]) -> AdapterStatus:
        status = self.last_http_status
        if status is None or status == 0 or status in {401, 403}:
            return AdapterStatus.BLOCKED
        if status != 200:
            return AdapterStatus.FAILED
        if not observations:
            return AdapterStatus.PARTIAL
        latest = observations[-1].period_end
        if latest is not None and latest.year < self._now().year:
            return AdapterStatus.PARTIAL
        return AdapterStatus.READY

    def _row_observations(
        self, artifact: HistoricalArtifact, row: dict[str, object]
    ) -> list[ParsedObservation]:
        parsed: list[ParsedObservation] = []
        for key, raw_value in row.items():
            match = _CELL.match(key)
            if match is None or not isinstance(raw_value, str):
                continue
            year_text, period_text, measure_text = match.groups()
            if measure_text != MEASURE_ID:
                continue
            month = MONTH_PERIOD_IDS.get(int(period_text))
            if month is None:
                continue
            value = _parse_decimal(raw_value)
            if value is None:
                continue
            year = int(year_text)
            period_end = date(year, month, calendar.monthrange(year, month)[1])
            limitations = ("explicit_zero",) if value == 0 else ()
            parsed.append(
                ParsedObservation(
                    metric_id="macro.cpi_mom",
                    source_id=self.source_id,
                    content_hash=artifact.content_hash,
                    normalization_version=PARSER_VERSION,
                    quality_status=RecordQuality.ACCEPTED,
                    value=value,
                    unit="percent",
                    period=f"{year:04d}-{month:02d}",
                    period_end=period_end,
                    reporting_standard="EMISS",
                    evidence=f"{SOURCE_URL}#{key}",
                    limitations=limitations,
                    extra={
                        "territory": TERRITORY_NAME,
                        "goods": GOODS_NAME,
                        "measure": "К предыдущему месяцу",
                        "cell": key,
                    },
                )
            )
        return parsed


def _cap(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, MAX_OBSERVATIONS)


def _load_json(raw: bytes) -> dict[str, object] | None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _count_cells(payload: dict[str, object]) -> int:
    count = 0
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        for key, raw_value in row.items():
            match = _CELL.match(str(key))
            if match is None or not isinstance(raw_value, str):
                continue
            if match.group(3) != MEASURE_ID:
                continue
            if int(match.group(2)) not in MONTH_PERIOD_IDS:
                continue
            if _parse_decimal(raw_value) is not None:
                count += 1
    return count


def _parse_decimal(text: str) -> float | None:
    cleaned = text.strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _fetch_status(http_status: int, parsed_count: int) -> FetchStatus:
    if http_status in {401, 403}:
        return FetchStatus.FORBIDDEN
    if http_status != 200:
        return FetchStatus.FAILED
    if parsed_count == 0:
        return FetchStatus.EMPTY
    return FetchStatus.OK


def _http_limitation(http_status: int) -> str:
    return f"http_status={http_status}"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _in_range(period_end: date | None, start: date | None, end: date | None) -> bool:
    if period_end is None:
        return False
    if start is not None and period_end < start:
        return False
    if end is not None and period_end > end:
        return False
    return True
