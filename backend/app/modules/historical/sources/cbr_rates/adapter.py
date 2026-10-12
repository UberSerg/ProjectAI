"""CBR-01 key rate, CBR-02 USD/RUB, and CBR-03 RUONIA.

Transport is ``CbrProvider`` (DailyInfo SOAP and XML_dynamic). This module
does not open a second HTTP stack. ``parse_cbr_soap`` does not read the
RUONIA ``ruo`` element, so row parsing of the raw body lives here.

Raw responses stay on disk under a caller-supplied directory (``.tmp``).
Nothing here writes prospective captures, signals, committee, shadow, or
broker tables.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree

import httpx

from app.domain.ports.market_data import ProviderFetchResult
from app.infrastructure.market.cbr import CbrProvider
from app.infrastructure.market.http_client import MarketHttpClient
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

PARSER_VERSION = "cbr_rates_v1"
NORMALIZATION_VERSION = "cbr_rates_v1"
MAX_SAMPLE_ROWS = 60
# Cross-year window already checked against the live feeds. Daily rows stay
# under the sample cap (key rate through 2024-02-29 is 62, so the end is 15 Feb).
SAMPLE_START = date(2023, 12, 1)
SAMPLE_END = date(2024, 2, 15)

_KEY_URL = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
_FX_URL = "https://www.cbr.ru/scripts/XML_dynamic.asp"


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    source_id: str
    external_id: str
    metric_id: str
    title: str
    unit: str
    source_url: str
    document_type: str
    entity_identifiers: dict[str, str]
    currency: str | None = None


SPECS: dict[str, SeriesSpec] = {
    "CBR-01": SeriesSpec(
        source_id="CBR-01",
        external_id="KEY_RATE",
        metric_id="macro.key_rate",
        title="CBR key rate",
        unit="percent",
        source_url=_KEY_URL,
        document_type="cbr_key_rate_xml",
        entity_identifiers={"soap_method": "KeyRateXML", "series": "KEY_RATE"},
    ),
    "CBR-02": SeriesSpec(
        source_id="CBR-02",
        external_id="USD_RUB_CBR",
        metric_id="macro.usd_rub_cbr",
        title="CBR official USD/RUB",
        unit="rub_per_unit",
        source_url=_FX_URL,
        document_type="cbr_fx_xml",
        currency="RUB",
        entity_identifiers={"cbr_code": "R01235", "currency": "USD", "series": "USD_RUB_CBR"},
    ),
    "CBR-03": SeriesSpec(
        source_id="CBR-03",
        external_id="RUONIA",
        metric_id="macro.ruonia",
        title="RUONIA",
        unit="percent",
        source_url=_KEY_URL,
        document_type="cbr_ruonia_xml",
        entity_identifiers={"soap_method": "RuoniaXML", "series": "RUONIA"},
    ),
}


@dataclass(frozen=True, slots=True)
class _Row:
    external_document_id: str
    period_end: date | None
    value: float | None
    quality_status: RecordQuality
    pit: PitQuality
    published_at: datetime | None
    published_at_precision: PublishedAtPrecision
    availability_evidence: str | None
    evidence: str | None
    limitations: tuple[str, ...]
    extra: dict[str, str]


class _SeriesFetcher(Protocol):
    def fetch_series(
        self, external_id: str, start_date: date, end_date: date
    ) -> ProviderFetchResult: ...


def open_series(source_id: str, **kwargs: object) -> CbrSeriesSource:
    try:
        spec = SPECS[source_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported CBR series: {source_id}") from exc
    return CbrSeriesSource(spec, **kwargs)  # type: ignore[arg-type]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse_decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    cleaned = text.strip().replace("\xa0", "").replace(" ", "")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned.replace(",", "."))
    except InvalidOperation:
        return None


def _parse_iso_datetime(text: str | None) -> datetime | None:
    if text is None or not text.strip():
        return None
    try:
        parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_fx_date(text: str | None) -> date | None:
    if text is None or len(text.strip()) < 10:
        return None
    try:
        return datetime.strptime(text.strip()[:10], "%d.%m.%Y").date()
    except ValueError:
        return None


def _is_html(raw: bytes) -> bool:
    head = raw.lstrip()[:240].lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or head.startswith(b"<head")


def _children(node: ElementTree.Element) -> dict[str, str | None]:
    return {_local(child.tag): child.text for child in list(node)}


def _clock_time(value: datetime) -> bool:
    return any((value.hour, value.minute, value.second, value.microsecond))


def _rate_quality(
    value: Decimal | None, *, missing: str, invalid: str
) -> tuple[RecordQuality, tuple[str, ...], float | None]:
    if value is None:
        return RecordQuality.QUARANTINE, (missing,), None
    if not value.is_finite():
        return RecordQuality.QUARANTINE, (invalid,), None
    if value == 0:
        return RecordQuality.QUARANTINE, ("source_literal_zero",), 0.0
    if value < 0:
        return RecordQuality.QUARANTINE, ("negative_value",), float(value)
    return RecordQuality.ACCEPTED, (), float(value)


def _publication_for_ruonia(
    period: date | None, updated: datetime | None
) -> tuple[PitQuality, datetime | None, PublishedAtPrecision, str | None, tuple[str, ...]]:
    if updated is None or period is None:
        return PitQuality.RESEARCH_ONLY, None, PublishedAtPrecision.UNKNOWN, None, ("ruonia_dateupdate_absent",)
    notes = ("DateUpdate_is_feed_update_time",)
    if updated.date() == period or not _clock_time(updated):
        # Same-day or midnight values are a publication date, not a verified timestamp.
        return PitQuality.PIT_PROXY, updated, PublishedAtPrecision.DATE_ONLY, "cbr_ruonia_DateUpdate", notes
    return PitQuality.PIT_VERIFIED, updated, PublishedAtPrecision.TIMESTAMP, "cbr_ruonia_DateUpdate", notes


def _mark_duplicates(rows: list[_Row]) -> list[_Row]:
    seen: set[date] = set()
    result: list[_Row] = []
    for row in rows:
        if row.period_end is not None and row.period_end in seen:
            result.append(
                _Row(
                    external_document_id=f"{row.external_document_id}#duplicate",
                    period_end=row.period_end,
                    value=row.value,
                    quality_status=RecordQuality.QUARANTINE,
                    pit=PitQuality.RESEARCH_ONLY,
                    published_at=row.published_at,
                    published_at_precision=row.published_at_precision,
                    availability_evidence=None,
                    evidence=None,
                    limitations=row.limitations + ("duplicate_period",),
                    extra=row.extra,
                )
            )
            continue
        if row.period_end is not None:
            seen.add(row.period_end)
        result.append(row)
    return result


def parse_key_rate_rows(raw: bytes) -> list[_Row]:
    root = ElementTree.fromstring(raw)
    rows: list[_Row] = []
    index = 0
    for node in root.iter():
        if _local(node.tag) != "KR":
            continue
        index += 1
        fields = _children(node)
        period_dt = _parse_iso_datetime(fields.get("DT"))
        period = period_dt.date() if period_dt is not None else None
        quality, notes, value = _rate_quality(
            _parse_decimal(fields.get("Rate")),
            missing="key_rate_missing",
            invalid="key_rate_not_a_number",
        )
        if period is None:
            quality = RecordQuality.QUARANTINE
            notes = notes + ("key_rate_date_missing",)
        row_id = f"CBR-01:{period.isoformat()}" if period is not None else f"CBR-01:unparsed-{index}"
        extra: dict[str, str] = {}
        if fields.get("Rate") is not None:
            extra["raw_rate"] = fields["Rate"] or ""
        rows.append(
            _Row(
                external_document_id=row_id,
                period_end=period,
                value=value,
                quality_status=quality,
                pit=PitQuality.RESEARCH_ONLY,
                published_at=None,
                published_at_precision=PublishedAtPrecision.UNKNOWN,
                availability_evidence=None,
                evidence=f"KeyRateXML/KR/{row_id}" if quality == RecordQuality.ACCEPTED else None,
                limitations=notes + ("cbr_dt_is_effective_date_not_publication_timestamp",),
                extra=extra,
            )
        )
    rows.sort(key=lambda row: (row.period_end is None, row.period_end or date.min, row.external_document_id))
    return _mark_duplicates(rows)


def parse_fx_rows(raw: bytes) -> list[_Row]:
    root = ElementTree.fromstring(raw)
    rows: list[_Row] = []
    index = 0
    for node in root.iter():
        if _local(node.tag) != "Record":
            continue
        index += 1
        attrs = {_local(key): value for key, value in node.attrib.items()}
        fields = _children(node)
        period = _parse_fx_date(attrs.get("Date") or fields.get("Date"))
        nominal = _parse_decimal(fields.get("Nominal"))
        quoted = _parse_decimal(fields.get("Value"))
        notes: tuple[str, ...] = ("cbr_fx_date_is_rate_date_not_publication_timestamp",)
        value: float | None = None
        quality = RecordQuality.ACCEPTED
        if quoted is None:
            quality = RecordQuality.QUARANTINE
            notes = notes + ("fx_value_missing",)
        elif nominal is None:
            quality = RecordQuality.QUARANTINE
            notes = notes + ("fx_nominal_missing",)
        elif nominal == 0:
            quality = RecordQuality.QUARANTINE
            notes = notes + ("fx_nominal_zero",)
        else:
            per_unit = quoted / nominal
            quality, rate_notes, value = _rate_quality(
                per_unit, missing="fx_value_missing", invalid="fx_value_not_a_number"
            )
            notes = notes + rate_notes
        if period is None:
            quality = RecordQuality.QUARANTINE
            notes = notes + ("fx_date_missing",)
        row_id = f"CBR-02:{period.isoformat()}" if period is not None else f"CBR-02:unparsed-{index}"
        extra = {
            "raw_value": fields.get("Value") or "",
            "raw_nominal": fields.get("Nominal") or "",
            "cbr_code": attrs.get("Id") or "",
        }
        rows.append(
            _Row(
                external_document_id=row_id,
                period_end=period,
                value=value,
                quality_status=quality,
                pit=PitQuality.RESEARCH_ONLY,
                published_at=None,
                published_at_precision=PublishedAtPrecision.UNKNOWN,
                availability_evidence=None,
                evidence=f"XML_dynamic/Record/{row_id}" if quality == RecordQuality.ACCEPTED else None,
                limitations=notes,
                extra=extra,
            )
        )
    rows.sort(key=lambda row: (row.period_end is None, row.period_end or date.min, row.external_document_id))
    return _mark_duplicates(rows)


def parse_ruonia_rows(raw: bytes) -> list[_Row]:
    root = ElementTree.fromstring(raw)
    rows: list[_Row] = []
    index = 0
    for node in root.iter():
        if _local(node.tag) != "ro":
            continue
        index += 1
        fields = _children(node)
        period_dt = _parse_iso_datetime(fields.get("D0"))
        period = period_dt.date() if period_dt is not None else None
        updated = _parse_iso_datetime(fields.get("DateUpdate"))
        quality, notes, value = _rate_quality(
            _parse_decimal(fields.get("ruo")),
            missing="ruonia_missing",
            invalid="ruonia_not_a_number",
        )
        if period is None:
            quality = RecordQuality.QUARANTINE
            notes = notes + ("ruonia_date_missing",)
        pit, published_at, precision, evidence_kind, pit_notes = _publication_for_ruonia(period, updated)
        notes = notes + pit_notes
        if quality != RecordQuality.ACCEPTED:
            pit = PitQuality.RESEARCH_ONLY
            evidence_kind = None
        volume = _parse_decimal(fields.get("vol"))
        extra: dict[str, str] = {}
        if fields.get("ruo") is not None:
            extra["raw_ruo"] = fields["ruo"] or ""
        if volume is not None:
            extra["volume_billion_rub"] = format(volume, "f")
        else:
            notes = notes + ("ruonia_volume_absent",)
        row_id = f"CBR-03:{period.isoformat()}" if period is not None else f"CBR-03:unparsed-{index}"
        rows.append(
            _Row(
                external_document_id=row_id,
                period_end=period,
                value=value,
                quality_status=quality,
                pit=pit,
                published_at=published_at,
                published_at_precision=precision,
                availability_evidence=evidence_kind,
                evidence=f"RuoniaXML/ro/{row_id}" if quality == RecordQuality.ACCEPTED else None,
                limitations=notes,
                extra=extra,
            )
        )
    rows.sort(key=lambda row: (row.period_end is None, row.period_end or date.min, row.external_document_id))
    return _mark_duplicates(rows)


_PARSERS = {
    "CBR-01": parse_key_rate_rows,
    "CBR-02": parse_fx_rows,
    "CBR-03": parse_ruonia_rows,
}


class CbrSeriesSource:
    source_id: str

    def __init__(
        self,
        spec: SeriesSpec,
        *,
        provider: _SeriesFetcher | None = None,
        now: datetime | None = None,
        clock: Callable[[], datetime] | None = None,
        raw_dir: Path | None = None,
    ) -> None:
        self.spec = spec
        self.source_id = spec.source_id
        self._provider = provider
        self._owns_provider = provider is None
        self._fixed_now = now
        self._clock = clock
        self._raw_dir = raw_dir
        self._last_raw: bytes | None = None
        self._last_artifacts: tuple[HistoricalArtifact, ...] = ()
        self._coverage_status = AdapterStatus.PENDING
        self._coverage_limitations: tuple[str, ...] = (
            f"endpoint={spec.source_url}",
            f"external_id={spec.external_id}",
        )

    def close(self) -> None:
        if not self._owns_provider or self._provider is None:
            return
        client = getattr(self._provider, "client", None)
        if client is not None and hasattr(client, "close"):
            client.close()

    def discover(self) -> CoverageReport:
        return CoverageReport(
            source_id=self.source_id,
            status=AdapterStatus.PENDING,
            earliest=None,
            latest=None,
            formats=("xml",),
            limitations=self._coverage_limitations + (f"sample={SAMPLE_START.isoformat()}..{SAMPLE_END.isoformat()}",),
        )

    def inspect_coverage(self) -> CoverageReport:
        dates = [item.period_end for item in self._last_artifacts if item.period_end is not None]
        return CoverageReport(
            source_id=self.source_id,
            status=self._coverage_status,
            earliest=min(dates) if dates else None,
            latest=max(dates) if dates else None,
            formats=("xml",),
            limitations=self._coverage_limitations,
        )

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        return self.fetch_range(start=SAMPLE_START, end=SAMPLE_END, limit=limit)

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        self._check_limit(limit)
        if end < start:
            raise ValueError("end precedes start")
        try:
            result = self._fetcher().fetch_series(self.spec.external_id, start, end)
        except httpx.HTTPStatusError as exc:
            status = _http_fetch_status(exc.response.status_code)
            blocked = status in {FetchStatus.FORBIDDEN, FetchStatus.RATE_LIMITED}
            adapter_status = AdapterStatus.BLOCKED if blocked else AdapterStatus.FAILED
            return self._fail(
                status,
                adapter_status,
                (f"http_{exc.response.status_code}",),
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return self._fail(FetchStatus.FAILED, AdapterStatus.FAILED, (type(exc).__name__,))
        raw_payloads = result.raw_payloads
        if not raw_payloads:
            return self._fail(FetchStatus.EMPTY, AdapterStatus.PARTIAL, ("empty_payload",))
        raw = raw_payloads[0]
        self._remember_raw(raw, start, end)
        return self._artifacts_from_raw(raw, limit, start=start, end=end)

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if artifact.fetch_status != FetchStatus.OK:
            return ()
        if artifact.content_hash != _sha256(raw):
            return (
                self._observation(
                    artifact,
                    _Row(
                        external_document_id=artifact.external_document_id,
                        period_end=artifact.period_end,
                        value=None,
                        quality_status=RecordQuality.QUARANTINE,
                        pit=PitQuality.RESEARCH_ONLY,
                        published_at=None,
                        published_at_precision=PublishedAtPrecision.UNKNOWN,
                        availability_evidence=None,
                        evidence=None,
                        limitations=("content_hash_mismatch",),
                        extra={},
                    ),
                ),
            )
        matched = [row for row in self._parse_rows(raw) if row.external_document_id == artifact.external_document_id]
        if not matched:
            return (
                self._observation(
                    artifact,
                    _Row(
                        external_document_id=artifact.external_document_id,
                        period_end=None,
                        value=None,
                        quality_status=RecordQuality.QUARANTINE,
                        pit=PitQuality.RESEARCH_ONLY,
                        published_at=None,
                        published_at_precision=PublishedAtPrecision.UNKNOWN,
                        availability_evidence=None,
                        evidence=None,
                        limitations=("row_not_in_payload",),
                        extra={},
                    ),
                ),
            )
        return tuple(self._observation(artifact, row) for row in matched)

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        checked: list[ParsedObservation] = []
        for observation in observations:
            errors = observation.quality_errors()
            if observation.quality_status == RecordQuality.ACCEPTED and errors:
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
                        evidence=observation.evidence,
                        limitations=observation.limitations + errors,
                        extra=dict(observation.extra),
                    )
                )
            else:
                checked.append(observation)
        return tuple(checked)

    def _fetcher(self) -> _SeriesFetcher:
        if self._provider is None:
            self._provider = CbrProvider(client=MarketHttpClient(max_retries=0, timeout=45.0))
        return self._provider

    def _now(self) -> datetime:
        if self._clock is not None:
            current = self._clock()
        elif self._fixed_now is not None:
            current = self._fixed_now
        else:
            current = datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("first_observed_at must be timezone-aware")
        return current

    def _check_limit(self, limit: int) -> None:
        if limit < 1 or limit > MAX_SAMPLE_ROWS:
            raise ValueError(f"limit must be between 1 and {MAX_SAMPLE_ROWS}")

    def _remember_raw(self, raw: bytes, start: date, end: date) -> None:
        self._last_raw = raw
        if self._raw_dir is None:
            return
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        path = self._raw_dir / f"{self.source_id}-{start.isoformat()}-{end.isoformat()}.xml"
        path.write_bytes(raw)

    def _parse_rows(self, raw: bytes) -> list[_Row]:
        if _is_html(raw):
            raise ValueError("html_payload")
        root = ElementTree.fromstring(raw)
        if any(_local(node.tag) == "Fault" for node in root.iter()):
            raise ValueError("soap_fault")
        return _PARSERS[self.source_id](raw)

    def _artifacts_from_raw(
        self, raw: bytes, limit: int, *, start: date, end: date
    ) -> tuple[HistoricalArtifact, ...]:
        observed_at = self._now()
        digest = _sha256(raw)
        try:
            rows = [
                row
                for row in self._parse_rows(raw)
                if row.period_end is None or start <= row.period_end <= end
            ]
        except ValueError as exc:
            reason = str(exc)
            status = AdapterStatus.PARTIAL if reason == "html_payload" else AdapterStatus.FAILED
            fetch_status = FetchStatus.UNSUPPORTED if reason == "html_payload" else FetchStatus.FAILED
            return self._fail(fetch_status, status, (reason,), content_hash=digest)
        except ElementTree.ParseError as exc:
            return self._fail(
                FetchStatus.FAILED,
                AdapterStatus.FAILED,
                (f"xml_parse_error:{exc}",),
                content_hash=digest,
            )
        selected = rows[:limit]
        if not selected:
            return self._fail(FetchStatus.EMPTY, AdapterStatus.PARTIAL, ("no_rows",), content_hash=digest)
        artifacts = tuple(self._artifact(row, observed_at, digest) for row in selected)
        accepted = [item for item in artifacts if item.quality_status == RecordQuality.ACCEPTED]
        self._last_artifacts = artifacts
        self._coverage_status = AdapterStatus.READY if accepted else AdapterStatus.PARTIAL
        self._coverage_limitations = self._coverage_limitations + (
            f"rows={len(artifacts)}",
            f"accepted={len(accepted)}",
            f"quarantine={len(artifacts) - len(accepted)}",
            f"pit={artifacts[0].historical_pit_quality.value}",
        )
        return artifacts

    def _artifact(self, row: _Row, observed_at: datetime, digest: str) -> HistoricalArtifact:
        # observed_at is the fetch clock. It is never the row's period_end.
        return HistoricalArtifact(
            source_id=self.source_id,
            source_url=self.spec.source_url,
            external_document_id=row.external_document_id,
            document_type=self.spec.document_type,
            content_hash=digest,
            parser_version=PARSER_VERSION,
            fetch_status=FetchStatus.OK,
            first_observed_at=observed_at,
            title=self.spec.title,
            entity_identifiers=dict(self.spec.entity_identifiers),
            reporting_period=row.period_end.isoformat() if row.period_end is not None else None,
            period_end=row.period_end,
            published_at=row.published_at,
            published_at_precision=row.published_at_precision,
            historical_availability_evidence=row.availability_evidence,
            historical_pit_quality=row.pit,
            raw_artifact_reference=digest,
            quality_status=row.quality_status,
            limitations=row.limitations,
        )

    def _observation(self, artifact: HistoricalArtifact, row: _Row) -> ParsedObservation:
        return ParsedObservation(
            metric_id=self.spec.metric_id,
            source_id=self.source_id,
            content_hash=artifact.content_hash,
            normalization_version=NORMALIZATION_VERSION,
            quality_status=row.quality_status,
            value=row.value,
            unit=self.spec.unit,
            currency=self.spec.currency,
            period=row.period_end.isoformat() if row.period_end is not None else None,
            period_end=row.period_end,
            evidence=row.evidence,
            limitations=row.limitations,
            extra=dict(row.extra),
        )

    def _fail(
        self,
        fetch_status: FetchStatus,
        adapter_status: AdapterStatus,
        limitations: tuple[str, ...],
        *,
        content_hash: str | None = None,
    ) -> tuple[HistoricalArtifact, ...]:
        digest = content_hash or _sha256("|".join(limitations).encode())
        artifact = HistoricalArtifact(
            source_id=self.source_id,
            source_url=self.spec.source_url,
            external_document_id=f"{self.source_id}:fetch-failed",
            document_type=self.spec.document_type,
            content_hash=digest,
            parser_version=PARSER_VERSION,
            fetch_status=fetch_status,
            first_observed_at=self._now(),
            title=self.spec.title,
            entity_identifiers=dict(self.spec.entity_identifiers),
            historical_pit_quality=PitQuality.RESEARCH_ONLY,
            quality_status=RecordQuality.UNRESOLVED,
            limitations=limitations,
        )
        self._last_artifacts = (artifact,)
        self._coverage_status = adapter_status
        self._coverage_limitations = self._coverage_limitations + limitations
        return (artifact,)


def _http_fetch_status(code: int) -> FetchStatus:
    if code == 403:
        return FetchStatus.FORBIDDEN
    if code == 429:
        return FetchStatus.RATE_LIMITED
    return FetchStatus.FAILED
