"""CBR-04 official gold accounting price.

Series is DragMetDynamicXML, metal code 1 (gold, rubles per gram).
It is not the key rate, USD/RUB, or RUONIA.

One live probe on 2026-10-13 returned HTTP 200 from
``https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx`` for
2024-01-09..2024-01-31. The body has 64 ``DrgMet`` rows. Gold is 16
of them, 2024-01-10..2024-01-31. ``DateMet`` is an accounting date at
midnight +03:00. The payload has no publication timestamp and no
availability evidence, so rows stay RESEARCH_ONLY.

Transport is ``MarketHttpClient`` plus the DailyInfo SOAP envelope
already built by ``CbrProvider``. This module does not open a second
HTTP stack. Tests pass a fetcher and do not call CBR.

Nothing here writes prospective captures, signals, committee, shadow,
or broker tables.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from xml.etree import ElementTree

import httpx

from app.core.config import get_settings
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

SOURCE_ID = "CBR-04"
PARSER_VERSION = "cbr_macro_gold_v1"
NORMALIZATION_VERSION = "cbr_macro_gold_v1"
MAX_SAMPLE_ROWS = 100
SAMPLE_START = date(2024, 1, 9)
SAMPLE_END = date(2024, 1, 31)
SOAP_METHOD = "DragMetDynamicXML"
GOLD_CODE = "1"
METRIC_ID = "macro.cbr_gold_rub_per_gram"
SOURCE_URL = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"

_ACCOUNTING_DATE = "cbr_datemet_is_accounting_date_not_publication_timestamp"


@dataclass(frozen=True, slots=True)
class _Row:
    external_document_id: str
    period_end: date | None
    value: float | None
    quality_status: RecordQuality
    evidence: str | None
    limitations: tuple[str, ...]
    extra: dict[str, str]


class _GoldFetcher(Protocol):
    def fetch_gold(self, start: date, end: date) -> bytes: ...


class _LiveDragMetFetcher:
    """POST DragMetDynamicXML through the existing market HTTP client."""

    def __init__(self) -> None:
        self._client: MarketHttpClient | None = None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def fetch_gold(self, start: date, end: date) -> bytes:
        if self._client is None:
            self._client = MarketHttpClient(max_retries=0, timeout=45.0)
        base = get_settings().cbr_base_url.rstrip("/")
        response = self._client.post(
            f"{base}/DailyInfoWebServ/DailyInfo.asmx",
            content=CbrProvider._soap_envelope(SOAP_METHOD, start, end),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f"http://web.cbr.ru/{SOAP_METHOD}",
            },
        )
        return response.content


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


def _is_html(raw: bytes) -> bool:
    head = raw.lstrip()[:240].lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head"))


def _children(node: ElementTree.Element) -> dict[str, str | None]:
    return {_local(child.tag): child.text for child in list(node)}


def _price_quality(value: Decimal | None) -> tuple[RecordQuality, tuple[str, ...], float | None]:
    if value is None:
        return RecordQuality.QUARANTINE, ("gold_price_missing",), None
    if not value.is_finite():
        return RecordQuality.QUARANTINE, ("gold_price_not_a_number",), None
    if value == 0:
        return RecordQuality.QUARANTINE, ("source_literal_zero",), 0.0
    if value < 0:
        return RecordQuality.QUARANTINE, ("negative_value",), float(value)
    return RecordQuality.ACCEPTED, (), float(value)


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


def parse_gold_rows(raw: bytes) -> list[_Row]:
    """Gold rows only. Other metal codes in the same body are ignored."""

    root = ElementTree.fromstring(raw)
    rows: list[_Row] = []
    index = 0
    for node in root.iter():
        if _local(node.tag) != "DrgMet":
            continue
        fields = _children(node)
        if (fields.get("CodMet") or "").strip() != GOLD_CODE:
            continue
        index += 1
        period_dt = _parse_iso_datetime(fields.get("DateMet"))
        period = period_dt.date() if period_dt is not None else None
        quality, notes, value = _price_quality(_parse_decimal(fields.get("price")))
        if period is None:
            quality = RecordQuality.QUARANTINE
            notes = notes + ("gold_date_missing",)
        row_id = f"CBR-04:{period.isoformat()}" if period is not None else f"CBR-04:unparsed-{index}"
        extra: dict[str, str] = {"metal_code": GOLD_CODE}
        if fields.get("price") is not None:
            extra["raw_price"] = fields["price"] or ""
        rows.append(
            _Row(
                external_document_id=row_id,
                period_end=period,
                value=value,
                quality_status=quality,
                evidence=f"DragMetDynamicXML/DrgMet/{row_id}" if quality == RecordQuality.ACCEPTED else None,
                limitations=notes + (_ACCOUNTING_DATE,),
                extra=extra,
            )
        )
    rows.sort(key=lambda row: (row.period_end is None, row.period_end or date.min, row.external_document_id))
    return _mark_duplicates(rows)


class CbrMacroSource:
    source_id = SOURCE_ID

    def __init__(
        self,
        *,
        fetcher: _GoldFetcher | None = None,
        now: datetime | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._owns_fetcher = fetcher is None
        self._fixed_now = now
        self._clock = clock
        self._last_artifacts: tuple[HistoricalArtifact, ...] = ()
        self._coverage_status = AdapterStatus.PENDING
        self._coverage_limitations: tuple[str, ...] = (
            f"endpoint={SOURCE_URL}",
            f"soap_method={SOAP_METHOD}",
            f"metal_code={GOLD_CODE}",
            _ACCOUNTING_DATE,
        )

    def close(self) -> None:
        if not self._owns_fetcher or self._fetcher is None:
            return
        close = getattr(self._fetcher, "close", None)
        if close is not None:
            close()

    def discover(self) -> CoverageReport:
        return CoverageReport(
            source_id=self.source_id,
            status=AdapterStatus.PENDING,
            earliest=None,
            latest=None,
            formats=("xml",),
            limitations=self._coverage_limitations
            + (f"sample={SAMPLE_START.isoformat()}..{SAMPLE_END.isoformat()}",),
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
            raw = self._client().fetch_gold(start, end)
        except httpx.HTTPStatusError as exc:
            status = _http_fetch_status(exc.response.status_code)
            blocked = status in {FetchStatus.FORBIDDEN, FetchStatus.RATE_LIMITED}
            adapter_status = AdapterStatus.BLOCKED if blocked else AdapterStatus.FAILED
            return self._fail(status, adapter_status, (f"http_{exc.response.status_code}",))
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return self._fail(FetchStatus.FAILED, AdapterStatus.FAILED, (type(exc).__name__,))
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

    def _client(self) -> _GoldFetcher:
        if self._fetcher is None:
            self._fetcher = _LiveDragMetFetcher()
        return self._fetcher

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

    def _parse_rows(self, raw: bytes) -> list[_Row]:
        if _is_html(raw):
            raise ValueError("html_payload")
        root = ElementTree.fromstring(raw)
        if any(_local(node.tag) == "Fault" for node in root.iter()):
            raise ValueError("soap_fault")
        return parse_gold_rows(raw)

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
        # observed_at is the fetch clock. DateMet is not a publication time.
        return HistoricalArtifact(
            source_id=self.source_id,
            source_url=SOURCE_URL,
            external_document_id=row.external_document_id,
            document_type="cbr_dragmet_gold_xml",
            content_hash=digest,
            parser_version=PARSER_VERSION,
            fetch_status=FetchStatus.OK,
            first_observed_at=observed_at,
            title="CBR gold accounting price",
            entity_identifiers={
                "soap_method": SOAP_METHOD,
                "series": "CBR_GOLD",
                "metal_code": GOLD_CODE,
                "metal": "gold",
            },
            reporting_period=row.period_end.isoformat() if row.period_end is not None else None,
            period_end=row.period_end,
            published_at=None,
            published_at_precision=PublishedAtPrecision.UNKNOWN,
            historical_availability_evidence=None,
            historical_pit_quality=PitQuality.RESEARCH_ONLY,
            raw_artifact_reference=digest,
            quality_status=row.quality_status,
            limitations=row.limitations,
        )

    def _observation(self, artifact: HistoricalArtifact, row: _Row) -> ParsedObservation:
        return ParsedObservation(
            metric_id=METRIC_ID,
            source_id=self.source_id,
            content_hash=artifact.content_hash,
            normalization_version=NORMALIZATION_VERSION,
            quality_status=row.quality_status,
            value=row.value,
            unit="rub_per_gram",
            currency="RUB",
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
            source_url=SOURCE_URL,
            external_document_id="CBR-04:fetch-failed",
            document_type="cbr_dragmet_gold_xml",
            content_hash=digest,
            parser_version=PARSER_VERSION,
            fetch_status=fetch_status,
            first_observed_at=self._now(),
            title="CBR gold accounting price",
            entity_identifiers={
                "soap_method": SOAP_METHOD,
                "series": "CBR_GOLD",
                "metal_code": GOLD_CODE,
            },
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
