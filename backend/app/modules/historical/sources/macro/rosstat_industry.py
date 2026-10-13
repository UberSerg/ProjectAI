"""ROS-02 industrial production and ROS-03 ILO unemployment via Fedstat dataGrid.

Verified on 2026-10-13 with ``UrllibTransport``. No CSRF token and no call to
``downloadData.do``.

ROS-02 is indicator 57806, the national OKVED2 industry grouping, month
compared with the same month a year earlier. The 2017-2024 grid returned
HTTP 200 and 72 months (2017-01..2022-12). 2023-2024 were in that request
and absent. A second window, 2025-2026, returned HTTP 200 and zero rows.

ROS-03 is indicator 43062, ILO unemployment for the Russian Federation,
age 15 and older. One grid for 2017-2026 returned HTTP 200 and 30 points
(quarters plus the annual value, 2017..2022). Later years were absent.

Each request stays within 100 period slots. Parsed observations are capped
at 100. Publication handling lives in ``rosstat_meta``.
"""

from __future__ import annotations

import calendar
import hashlib
import html
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.error import URLError

from app.modules.historical.application.adapter import CoverageReport
from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    HistoricalArtifact,
    ParsedObservation,
    RecordQuality,
)
from app.modules.historical.sources.macro.rosstat_cpi import MONTH_PERIOD_IDS
from app.modules.historical.sources.macro.rosstat_meta import (
    PublicationFacts,
    assess_publication,
    load_json_object,
)
from app.modules.historical.sources.macro.transport import HttpResult, Transport, UrllibTransport

MAX_OBSERVATIONS = 100
SERIES_START_YEAR = 2017
TERRITORY_NAME = "Российская Федерация"
_CELL = re.compile(r"^dim(\d{4})_(\d+)_d\d+_i\d+$")


@dataclass(frozen=True, slots=True)
class _Period:
    label: str
    end_month: int


@dataclass(frozen=True, slots=True)
class _SeriesSpec:
    source_id: str
    indicator_id: str
    title: str
    metric_id: str
    document_slug: str
    parser_version: str
    line_object_ids: tuple[str, ...]
    column_object_ids: tuple[str, ...]
    filter_object_ids: tuple[str, ...]
    selected_filters: tuple[tuple[str, str], ...]
    periods: dict[int, _Period]
    row_labels: dict[str, str]
    measure: str


def _month_periods() -> dict[int, _Period]:
    return {
        period_id: _Period(label=f"{month:02d}", end_month=month)
        for period_id, month in MONTH_PERIOD_IDS.items()
    }


INDUSTRY_ACTIVITY = (
    "Собирательная классификационная группировка видов экономической деятельности "
    '"Промышленность" на основе ОКВЭД2 (КДЕС Ред. 2)'
)
INDUSTRY_MEASURE = "Отчетный месяц к соответствующему месяцу предыдущего года"
UNEMPLOYMENT_TITLE = "Уровень безработицы (по методологии МОТ)"
UNEMPLOYMENT_AGE = "15 лет и старше"

INDUSTRY_SPEC = _SeriesSpec(
    source_id="ROS-02",
    indicator_id="57806",
    title="Индекс производства (оперативные данные) (ОКВЭД2)",
    metric_id="macro.industrial_production_yoy",
    document_slug="ippi-yoy-rf",
    parser_version="rosstat_ippi_emiss_v1",
    line_object_ids=("57940", "57937", "57831"),
    column_object_ids=("3", "33560"),
    filter_object_ids=("30611",),
    selected_filters=(
        ("0", "57806"),
        ("57940", "1751132"),
        ("57937", "1704141"),
        ("57831", "1688487"),
        ("30611", "950473"),
    ),
    periods=_month_periods(),
    row_labels={
        "dim57940": INDUSTRY_ACTIVITY,
        "dim57937": INDUSTRY_MEASURE,
        "dim57831": TERRITORY_NAME,
    },
    measure=INDUSTRY_MEASURE,
)
UNEMPLOYMENT_SPEC = _SeriesSpec(
    source_id="ROS-03",
    indicator_id="43062",
    title=UNEMPLOYMENT_TITLE,
    metric_id="macro.unemployment_ilo",
    document_slug="unemployment-ilo-rf",
    parser_version="rosstat_unemployment_emiss_v1",
    line_object_ids=("58335", "57831", "30611", "0"),
    column_object_ids=("3", "33560"),
    filter_object_ids=(),
    selected_filters=(
        ("0", "43062"),
        ("58335", "1788561"),
        ("57831", "1688487"),
        ("30611", "950473"),
    ),
    periods={
        1540222: _Period("Q1", 3),
        1540224: _Period("Q2", 6),
        1540226: _Period("Q3", 9),
        1540227: _Period("Q4", 12),
        1558883: _Period("Y", 12),
    },
    row_labels={
        "dim58335": UNEMPLOYMENT_AGE,
        "dim57831": TERRITORY_NAME,
        "dim30611": "процент",
        "dim0": UNEMPLOYMENT_TITLE,
    },
    measure=UNEMPLOYMENT_TITLE,
)

INDUSTRY_GRID_URL = "https://www.fedstat.ru/indicator/dataGrid.do?id=57806"
INDUSTRY_PAGE_URL = "https://www.fedstat.ru/indicator/57806"
UNEMPLOYMENT_GRID_URL = "https://www.fedstat.ru/indicator/dataGrid.do?id=43062"
UNEMPLOYMENT_PAGE_URL = "https://www.fedstat.ru/indicator/43062"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _FedstatSeriesSource:
    source_id: str

    def __init__(
        self,
        spec: _SeriesSpec,
        transport: Transport | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._spec = spec
        self.source_id = spec.source_id
        self._transport = transport if transport is not None else UrllibTransport()
        self._now = now if now is not None else _utcnow
        self.last_raw: bytes = b""
        self.last_http_status: int | None = None
        self.recent_http_status: int | None = None
        self.passport_http_status: int | None = None
        self.publication_status: AdapterStatus = AdapterStatus.PENDING
        self.publication_timestamp_present = False
        self._bodies: dict[str, bytes] = {}
        self._grid_statuses: list[int] = []
        self.last_artifacts: tuple[HistoricalArtifact, ...] = ()

    def discover(self) -> CoverageReport:
        artifacts = self.fetch_sample(limit=MAX_OBSERVATIONS)
        observations = self._collect(artifacts, MAX_OBSERVATIONS)
        earliest = observations[0].period_end if observations else None
        latest = observations[-1].period_end if observations else None
        limitations: list[str] = []
        for artifact in artifacts:
            limitations.extend(artifact.limitations)
        return CoverageReport(
            source_id=self.source_id,
            status=self._series_status(observations),
            earliest=earliest,
            latest=latest,
            formats=("json", "html"),
            limitations=tuple(dict.fromkeys(limitations)),
        )

    def inspect_coverage(self) -> CoverageReport:
        return self.discover()

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        return self._load(limit=_cap(limit), start=None, end=None)

    def fetch_range(
        self, *, start: date, end: date, limit: int
    ) -> tuple[HistoricalArtifact, ...]:
        return self._load(limit=_cap(limit), start=start, end=end)

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if artifact.fetch_status is not FetchStatus.OK:
            return ()
        payload = load_json_object(raw)
        if payload is None:
            return ()
        observations: list[ParsedObservation] = []
        for row in payload.get("results") or []:
            if not isinstance(row, dict):
                continue
            if not _row_matches(row, self._spec.row_labels):
                continue
            observations.extend(self._row_observations(artifact, row))
        observations.sort(key=_observation_sort)
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

    def raw_for(self, artifact: HistoricalArtifact) -> bytes:
        return self._bodies.get(artifact.content_hash, b"")

    def _collect(
        self, artifacts: tuple[HistoricalArtifact, ...], limit: int
    ) -> tuple[ParsedObservation, ...]:
        merged: list[ParsedObservation] = []
        for artifact in artifacts:
            merged.extend(self.parse(artifact, self.raw_for(artifact)))
        merged.sort(key=_observation_sort)
        return tuple(merged[-_cap(limit) :])

    def _load(
        self, *, limit: int, start: date | None, end: date | None
    ) -> tuple[HistoricalArtifact, ...]:
        fetched_at = self._now()
        end_year = fetched_at.year
        windows = _year_windows(end_year, len(self._spec.periods))
        grid_results: list[tuple[int, int, HttpResult]] = []
        self._grid_statuses = []
        self.recent_http_status = None
        self.last_http_status = None
        self.last_raw = b""
        for start_year, stop_year in windows:
            result = self._request(
                _grid_url(self._spec.indicator_id),
                data=self._query_body(start_year, stop_year),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            grid_results.append((start_year, stop_year, result))
            self._grid_statuses.append(result.status)
            if start_year == SERIES_START_YEAR:
                self.last_http_status = result.status
                self.last_raw = result.body
            else:
                self.recent_http_status = result.status
        passport = self._request(
            _page_url(self._spec.indicator_id),
            headers={"Accept": "text/html"},
        )
        self.passport_http_status = passport.status
        facts = assess_publication(
            grid_bodies=tuple(item[2].body for item in grid_results),
            passport_body=passport.body,
            passport_status=passport.status,
        )
        self.publication_status = facts.status
        self.publication_timestamp_present = facts.timestamp_present
        artifacts: list[HistoricalArtifact] = []
        for start_year, stop_year, result in grid_results:
            artifact = self._artifact(
                result.body,
                result.status,
                fetched_at,
                facts=facts,
                passport_status=passport.status,
                limit=limit,
                start=start,
                end=end,
                start_year=start_year,
                stop_year=stop_year,
            )
            self._bodies[artifact.content_hash] = result.body
            artifacts.append(artifact)
        self.last_artifacts = tuple(artifacts)
        return self.last_artifacts

    def _query_body(self, start_year: int, stop_year: int) -> bytes:
        parts = [f"lineObjectIds={item}" for item in self._spec.line_object_ids]
        parts.extend(f"columnObjectIds={item}" for item in self._spec.column_object_ids)
        parts.extend(f"filterObjectIds={item}" for item in self._spec.filter_object_ids)
        parts.extend(
            f"selectedFilterIds={field}_{value}" for field, value in self._spec.selected_filters
        )
        for period_id, _period in sorted(
            self._spec.periods.items(),
            key=lambda item: (item[1].end_month, item[1].label),
        ):
            parts.append(f"selectedFilterIds=33560_{period_id}")
        parts.extend(
            f"selectedFilterIds=3_{year}" for year in range(start_year, stop_year + 1)
        )
        return "&".join(parts).encode("ascii")

    def _request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        try:
            return self._transport.request(url, data=data, headers=headers)
        except URLError as exc:
            body = str(exc.reason).encode("utf-8", errors="replace")
            return HttpResult(url=url, status=0, body=body)

    def _artifact(
        self,
        raw: bytes,
        http_status: int,
        fetched_at: datetime,
        *,
        facts: PublicationFacts,
        passport_status: int,
        limit: int,
        start: date | None,
        end: date | None,
        start_year: int,
        stop_year: int,
    ) -> HistoricalArtifact:
        payload = load_json_object(raw) if http_status == 200 else None
        parsed_count, last_year = _cell_stats(payload, self._spec) if payload is not None else (0, None)
        fetch_status = _fetch_status(http_status, parsed_count)
        limitations = [
            f"http_status={http_status}",
            f"window={start_year}-{stop_year}",
            *facts.limitations,
        ]
        if http_status == 200 and parsed_count == 0:
            limitations.append("window_empty")
        if last_year is not None and last_year < stop_year:
            limitations.append(f"grid_last_year={last_year}")
            limitations.append(f"requested_through={stop_year}")
        identifiers = {
            "indicator_id": self._spec.indicator_id,
            "http_status": str(http_status),
            "passport_http_status": str(passport_status),
            "observation_limit": str(limit),
            "window_start": str(start_year),
            "window_end": str(stop_year),
            "page_url": _page_url(self._spec.indicator_id),
            "publication_timestamp_present": "true" if facts.timestamp_present else "false",
        }
        if facts.data_updated_on is not None:
            identifiers["data_updated_on"] = facts.data_updated_on.isoformat()
        if start is not None:
            identifiers["range_start"] = start.isoformat()
        if end is not None:
            identifiers["range_end"] = end.isoformat()
        return HistoricalArtifact(
            source_id=self.source_id,
            source_url=_grid_url(self._spec.indicator_id),
            external_document_id=(
                f"fedstat-{self._spec.indicator_id}-{self._spec.document_slug}-{start_year}-{stop_year}"
            ),
            document_type="macro_series",
            content_hash=hashlib.sha256(raw).hexdigest(),
            parser_version=self._spec.parser_version,
            fetch_status=fetch_status,
            first_observed_at=fetched_at,
            title=self._spec.title,
            entity_identifiers=identifiers,
            published_at=facts.published_at,
            published_at_precision=facts.precision,
            historical_availability_evidence=facts.evidence,
            historical_pit_quality=facts.pit_quality,
            quality_status=(
                RecordQuality.ACCEPTED if fetch_status is FetchStatus.OK else RecordQuality.UNRESOLVED
            ),
            limitations=tuple(dict.fromkeys(limitations)),
        )

    def _series_status(self, observations: tuple[ParsedObservation, ...]) -> AdapterStatus:
        statuses = self._grid_statuses
        blocked = {0, 401, 403}
        if statuses and all(status in blocked for status in statuses):
            return AdapterStatus.BLOCKED
        if not observations:
            if any(status == 200 for status in statuses):
                return AdapterStatus.PARTIAL
            if any(status in blocked for status in statuses):
                return AdapterStatus.BLOCKED
            return AdapterStatus.FAILED
        latest = observations[-1].period_end
        if latest is not None and latest.year < self._now().year:
            return AdapterStatus.PARTIAL
        if any(status != 200 for status in statuses):
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
            year_text, period_text = match.groups()
            period = self._spec.periods.get(int(period_text))
            if period is None:
                continue
            value = _parse_decimal(raw_value)
            if value is None:
                continue
            year = int(year_text)
            limitations = ("explicit_zero",) if value == 0 else ()
            parsed.append(
                ParsedObservation(
                    metric_id=self._spec.metric_id,
                    source_id=self.source_id,
                    content_hash=artifact.content_hash,
                    normalization_version=self._spec.parser_version,
                    quality_status=RecordQuality.ACCEPTED,
                    value=value,
                    unit="percent",
                    period=_period_text(year, period),
                    period_end=_period_end(year, period),
                    reporting_standard="EMISS",
                    evidence=f"{_grid_url(self._spec.indicator_id)}#{key}",
                    limitations=limitations,
                    extra={
                        "territory": TERRITORY_NAME,
                        "measure": self._spec.measure,
                        "frequency": _frequency(period),
                        "cell": key,
                    },
                )
            )
        return parsed


class RosstatIndustrialProductionSource(_FedstatSeriesSource):
    source_id = INDUSTRY_SPEC.source_id

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(INDUSTRY_SPEC, transport, now=now)


class RosstatUnemploymentSource(_FedstatSeriesSource):
    source_id = UNEMPLOYMENT_SPEC.source_id

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(UNEMPLOYMENT_SPEC, transport, now=now)


def _grid_url(indicator_id: str) -> str:
    return f"https://www.fedstat.ru/indicator/dataGrid.do?id={indicator_id}"


def _page_url(indicator_id: str) -> str:
    return f"https://www.fedstat.ru/indicator/{indicator_id}"


def _year_windows(end_year: int, slots_per_year: int) -> tuple[tuple[int, int], ...]:
    width = max(1, MAX_OBSERVATIONS // max(slots_per_year, 1))
    windows: list[tuple[int, int]] = []
    start = SERIES_START_YEAR
    last = max(end_year, SERIES_START_YEAR)
    while start <= last:
        stop = min(last, start + width - 1)
        windows.append((start, stop))
        start = stop + 1
    return tuple(windows)


def _cap(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, MAX_OBSERVATIONS)


def _row_matches(row: dict[str, object], labels: dict[str, str]) -> bool:
    for key, expected in labels.items():
        raw = row.get(key)
        if not isinstance(raw, str) or html.unescape(raw) != expected:
            return False
    return True


def _cell_stats(payload: dict[str, object], spec: _SeriesSpec) -> tuple[int, int | None]:
    count = 0
    last_year: int | None = None
    for row in payload.get("results") or []:
        if not isinstance(row, dict) or not _row_matches(row, spec.row_labels):
            continue
        for key, raw_value in row.items():
            match = _CELL.match(str(key))
            if match is None or not isinstance(raw_value, str):
                continue
            if int(match.group(2)) not in spec.periods:
                continue
            if _parse_decimal(raw_value) is None:
                continue
            count += 1
            year = int(match.group(1))
            if last_year is None or year > last_year:
                last_year = year
    return count, last_year


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


def _period_end(year: int, period: _Period) -> date:
    return date(year, period.end_month, calendar.monthrange(year, period.end_month)[1])


def _period_text(year: int, period: _Period) -> str:
    if period.label == "Y":
        return f"{year:04d}"
    return f"{year:04d}-{period.label}"


def _frequency(period: _Period) -> str:
    if period.label == "Y":
        return "year"
    if period.label.startswith("Q"):
        return "quarter"
    return "month"


def _observation_sort(item: ParsedObservation) -> tuple[date, str]:
    return (item.period_end or date.min, item.period or "")
