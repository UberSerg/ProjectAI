"""INT-03 and INT-04: one public official commodity series, no secret.

Discovery on 2026-10-13, certificate checks left on, no API key sent:

- World Bank ``CRUDE_BRENT`` (source 86, 2018M01:2026M04) returned HTTP 200
  and message id 120 ``Invalid value``. That body has no prices.
- IMF PCPS at ``api.imf.org`` failed TLS certificate verification. The check
  was not disabled.
- EIA was not requested.

The series that returned data is the Bank of Russia precious-metal
accounting quotations:

``https://www.cbr.ru/scripts/xml_metall.asp?date_req1=01/09/2026&date_req2=30/09/2026``

HTTP 200, XML, 88 records, 2026-09-01..2026-09-30. The document has a
quotation date and Buy/Sell. It has no publication timestamp, so PIT stays
``RESEARCH_ONLY``.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
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

SOURCE_ID = "INT-03"
CONTEXT_STREAM_ID = "INT-04"
SOURCE_NAME = "Bank of Russia precious metals quotations"
SOURCE_URL = "https://www.cbr.ru/scripts/xml_metall.asp?date_req1=01/09/2026&date_req2=30/09/2026"
PARSER_VERSION = "cbr_xml_metall_v1"
MAX_OBSERVATIONS = 100
WINDOW_START = date(2026, 9, 1)
WINDOW_END = date(2026, 9, 30)

# CBR DragMet code table. These names are not attributes of xml_metall.asp.
DOCUMENTED_METAL_NAMES: dict[str, str] = {
    "1": "gold",
    "2": "silver",
    "3": "platinum",
    "4": "palladium",
}

DISCOVERY_NOTES: tuple[str, ...] = (
    "world_bank_crude_brent_http_200_invalid_value",
    "imf_pcps_tls_certificate_verify_failed",
    "eia_not_requested",
    "cbr_xml_metall_http_200",
)

_CHALLENGE_MARKERS = (
    b"cf-challenge",
    b"cf-browser-verification",
    b"g-recaptcha",
    b"captcha",
    b"just a moment",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AccessCheck:
    stream_id: str
    source_url: str
    http_status: int | None
    blocked: bool
    challenge: bool
    api_key_sent: bool
    row_count: int
    status: AdapterStatus


@dataclass(frozen=True, slots=True)
class CommoditySeriesContext:
    metal_code: str
    documented_name: str | None
    name_in_payload: bool
    observation_count: int
    earliest: date | None
    latest: date | None
    unit_in_payload: bool


@dataclass(frozen=True, slots=True)
class CommodityContextMap:
    stream_id: str
    source_name: str
    source_url: str
    http_status: int | None
    status: AdapterStatus
    pit_quality: PitQuality
    publication_timestamp_present: bool
    row_count: int
    earliest: date | None
    latest: date | None
    series: tuple[CommoditySeriesContext, ...]
    limitations: tuple[str, ...]


class OfficialMacroSource:
    """Bounded CBR metal probe shared by INT-03 and INT-04."""

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
        self._artifact: HistoricalArtifact | None = None
        self._challenge = False

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
            formats=("xml",),
            limitations=artifact.limitations,
        )

    def inspect_coverage(self) -> CoverageReport:
        return self.discover()

    def access_check(self) -> AccessCheck:
        if self._artifact is None:
            self.discover()
        artifact = self._artifact
        assert artifact is not None
        observations = self.parse(artifact, self.last_raw)
        blocked = artifact.fetch_status in {FetchStatus.FORBIDDEN, FetchStatus.UNSUPPORTED}
        return AccessCheck(
            stream_id=SOURCE_ID,
            source_url=SOURCE_URL,
            http_status=self.last_http_status,
            blocked=blocked or self._challenge,
            challenge=self._challenge,
            api_key_sent=False,
            row_count=len(observations),
            status=self._adapter_status(observations),
        )

    def context_map(self) -> CommodityContextMap:
        if self._artifact is None:
            self.discover()
        artifact = self._artifact
        assert artifact is not None
        return _context_map(
            artifact,
            self.parse(artifact, self.last_raw),
            http_status=self.last_http_status,
        )

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        return (self._load(limit=_cap(limit), start=None, end=None),)

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        return (self._load(limit=_cap(limit), start=start, end=end),)

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if artifact.fetch_status is not FetchStatus.OK:
            return ()
        records = _records(raw)
        if records is None:
            return ()
        observations: list[ParsedObservation] = []
        for record in records:
            parsed = _observation(artifact, record)
            if parsed is not None:
                observations.append(parsed)
        observations.sort(key=lambda item: (item.period_end or date.min, item.extra.get("metal_code", "")))
        start = _parse_iso(artifact.entity_identifiers.get("range_start"))
        end = _parse_iso(artifact.entity_identifiers.get("range_end"))
        ranged = [item for item in observations if _in_range(item.period_end, start, end)]
        limit = _cap(int(artifact.entity_identifiers.get("observation_limit") or MAX_OBSERVATIONS))
        return tuple(ranged[-limit:])

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
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

    def _load(self, *, limit: int, start: date | None, end: date | None) -> HistoricalArtifact:
        result = self._fetch()
        artifact = _artifact(
            result.body,
            result.status,
            self._fetched_at(),
            limit=limit,
            start=start,
            end=end,
            challenge=self._challenge,
        )
        self._artifact = artifact
        return artifact

    def _fetch(self) -> HttpResult:
        try:
            result = self._transport.request(SOURCE_URL)
        except URLError as exc:
            body = str(exc.reason).encode("utf-8", errors="replace")
            self.last_http_status = 0
            self.last_raw = body
            self._challenge = False
            return HttpResult(url=SOURCE_URL, status=0, body=body)
        self.last_http_status = result.status
        self.last_raw = result.body
        self._challenge = _is_challenge(result.body)
        return result

    def _fetched_at(self) -> datetime:
        current = self._now()
        if current.tzinfo is None:
            raise ValueError("first_observed_at must be timezone-aware")
        return current

    def _adapter_status(self, observations: tuple[ParsedObservation, ...]) -> AdapterStatus:
        if self._artifact is None:
            return AdapterStatus.PENDING
        if self._challenge or self.last_http_status in {401, 403}:
            return AdapterStatus.BLOCKED
        if self.last_http_status in {None, 0} or self.last_http_status != 200:
            return AdapterStatus.FAILED
        if not observations:
            return AdapterStatus.PARTIAL
        return AdapterStatus.READY


def _context_map(
    artifact: HistoricalArtifact,
    observations: tuple[ParsedObservation, ...],
    *,
    http_status: int | None,
) -> CommodityContextMap:
    grouped: dict[str, list[ParsedObservation]] = {}
    for observation in observations:
        code = str(observation.extra.get("metal_code") or "")
        grouped.setdefault(code, []).append(observation)
    series: list[CommoditySeriesContext] = []
    for code in sorted(grouped):
        rows = grouped[code]
        dates = [item.period_end for item in rows if item.period_end is not None]
        series.append(
            CommoditySeriesContext(
                metal_code=code,
                documented_name=DOCUMENTED_METAL_NAMES.get(code),
                name_in_payload=False,
                observation_count=len(rows),
                earliest=dates[0] if dates else None,
                latest=dates[-1] if dates else None,
                unit_in_payload=False,
            )
        )
    earliest = observations[0].period_end if observations else None
    latest = observations[-1].period_end if observations else None
    blocked = artifact.fetch_status in {FetchStatus.FORBIDDEN, FetchStatus.UNSUPPORTED}
    if blocked or http_status in {401, 403}:
        status = AdapterStatus.BLOCKED
    elif http_status != 200:
        status = AdapterStatus.FAILED
    elif not observations:
        status = AdapterStatus.PARTIAL
    else:
        status = AdapterStatus.READY
    return CommodityContextMap(
        stream_id=CONTEXT_STREAM_ID,
        source_name=SOURCE_NAME,
        source_url=SOURCE_URL,
        http_status=http_status,
        status=status,
        pit_quality=PitQuality.RESEARCH_ONLY,
        publication_timestamp_present=False,
        row_count=len(observations),
        earliest=earliest,
        latest=latest,
        series=tuple(series),
        limitations=artifact.limitations,
    )


def _artifact(
    raw: bytes,
    http_status: int,
    fetched_at: datetime,
    *,
    limit: int,
    start: date | None,
    end: date | None,
    challenge: bool,
) -> HistoricalArtifact:
    blocked = challenge or http_status in {401, 403}
    records = None if blocked or http_status != 200 else _records(raw)
    parsed_count = 0 if records is None else sum(1 for record in records if _has_buy(record))
    if blocked and challenge and http_status not in {401, 403}:
        fetch_status = FetchStatus.UNSUPPORTED
    elif blocked:
        fetch_status = FetchStatus.FORBIDDEN
    elif http_status == 200 and parsed_count > 0:
        fetch_status = FetchStatus.OK
    elif http_status == 200:
        fetch_status = FetchStatus.EMPTY
    elif http_status == 429:
        fetch_status = FetchStatus.RATE_LIMITED
    else:
        fetch_status = FetchStatus.FAILED
    limitations = [
        f"http_status={http_status}",
        "api_key_not_sent",
        "no_publication_timestamp",
        "quotation_date_is_effective_date",
        "unit_not_in_xml",
        "metal_name_not_in_xml",
        "pilot_not_archive",
        f"bounded_window={WINDOW_START.isoformat()}..{WINDOW_END.isoformat()}",
    ]
    if challenge:
        limitations.append("challenge_page")
    identifiers = {
        "http_status": str(http_status),
        "observation_limit": str(limit),
        "api_key_sent": "false",
    }
    if start is not None:
        identifiers["range_start"] = start.isoformat()
    if end is not None:
        identifiers["range_end"] = end.isoformat()
    return HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=SOURCE_URL,
        external_document_id="cbr-xml-metall-2026-09",
        document_type="macro_series",
        content_hash=hashlib.sha256(raw).hexdigest(),
        parser_version=PARSER_VERSION,
        fetch_status=fetch_status,
        first_observed_at=fetched_at,
        title=SOURCE_NAME,
        entity_identifiers=identifiers,
        published_at=None,
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_availability_evidence=None,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        quality_status=(RecordQuality.ACCEPTED if fetch_status is FetchStatus.OK else RecordQuality.UNRESOLVED),
        limitations=tuple(limitations),
    )


def _observation(artifact: HistoricalArtifact, record: ElementTree.Element) -> ParsedObservation | None:
    quotation_date, code, buy, sell = _observation_fields(record)
    if quotation_date is None or code is None or buy is None:
        return None
    limitations: list[str] = []
    if buy == 0:
        limitations.append("explicit_zero")
    if sell is not None and sell != buy:
        limitations.append("buy_sell_differ")
    extra: dict[str, object] = {"metal_code": code}
    if sell is not None:
        extra["sell"] = sell
    return ParsedObservation(
        metric_id="commodity.cbr_accounting_price",
        source_id=SOURCE_ID,
        content_hash=artifact.content_hash,
        normalization_version=PARSER_VERSION,
        quality_status=RecordQuality.ACCEPTED,
        value=buy,
        unit=None,
        currency=None,
        period=quotation_date.isoformat(),
        period_end=quotation_date,
        evidence=f"cbr.xml_metall Date={quotation_date.isoformat()} Code={code} Buy",
        limitations=tuple(limitations),
        extra=extra,
    )


def _has_buy(record: ElementTree.Element) -> bool:
    quotation_date, code, buy, _sell = _observation_fields(record)
    return quotation_date is not None and code is not None and buy is not None


def _observation_fields(
    record: ElementTree.Element,
) -> tuple[date | None, str | None, float | None, float | None]:
    if _local(record.tag) != "Record":
        return None, None, None, None
    quotation_date = _parse_quotation_date(record.attrib.get("Date", ""))
    code = record.attrib.get("Code")
    if code is not None:
        code = code.strip() or None
    buy = _child_decimal(record, "Buy")
    sell = _child_decimal(record, "Sell")
    return quotation_date, code, buy, sell


def _records(raw: bytes) -> tuple[ElementTree.Element, ...] | None:
    if _is_challenge(raw):
        return None
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return None
    if _local(root.tag) != "Metall":
        return None
    return tuple(child for child in list(root) if _local(child.tag) == "Record")


def _child_decimal(record: ElementTree.Element, name: str) -> float | None:
    for child in list(record):
        if _local(child.tag) == name and child.text:
            return _parse_decimal(child.text)
    return None


def _parse_decimal(text: str) -> float | None:
    normalized = text.strip().replace(" ", "").replace(",", ".")
    if not normalized:
        return None
    try:
        return float(Decimal(normalized))
    except InvalidOperation:
        return None


def _parse_quotation_date(text: str) -> date | None:
    parts = text.split(".")
    if len(parts) != 3:
        return None
    try:
        day, month, year = (int(part) for part in parts)
        return date(year, month, day)
    except ValueError:
        return None


def _parse_iso(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _in_range(value: date | None, start: date | None, end: date | None) -> bool:
    if value is None:
        return False
    if start is not None and value < start:
        return False
    if end is not None and value > end:
        return False
    return True


def _is_challenge(body: bytes) -> bool:
    head = body.lstrip()[:64].lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return True
    lowered = body.lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _cap(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, MAX_OBSERVATIONS)
