"""IR-05 dividend archive for one issuer, from a public IR workbook.

The workbook is the Lukoil declared-dividends file already parsed by
``parse_lukoil_declared_sheet``. This module does not call MOEX CCI, does not
write prospective captures, and does not run a stage-1000 backfill.

Record date, per-share amount, and payment date are stored only when the sheet
has them. The payment-year column and footnote deadlines (``не позднее``) are
not a payment date. ``period_end`` is the calendar end of the results-period
label. A registry close, an AGM date inside the period text, and a payment
year are not ``period_end`` and are not a publication timestamp.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Protocol
from zipfile import BadZipFile

import httpx
from openpyxl.utils.exceptions import InvalidFileException

from app.modules.fundamentals.infrastructure.issuer_ir_xlsx_dividend_provider import (
    LUKOIL_DECLARED_URL,
    _clean_text,
    _sheet_rows,
    parse_russian_date,
)
from app.modules.fundamentals.infrastructure.lukoil_ir_xlsx import (
    parse_lukoil_amount,
    parse_lukoil_declared_sheet,
)
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

SOURCE_ID = "IR-05"
PARSER_VERSION = "issuer_dividends_ir05_v1"
NORMALIZATION_VERSION = "issuer_dividend_dps_v1"
EVENT_CAP = 30
SECID = "LKOH"
SOURCE_URL = LUKOIL_DECLARED_URL
METRIC_ID = "issuer.dividend.amount_per_share"

_PAYMENT_HEADER_MARKERS = ("дата выплаты", "дата платежа", "payment date")
_WORKBOOK_ERRORS = (BadZipFile, InvalidFileException, ValueError, KeyError, OSError)


class Transport(Protocol):
    def get(self, url: str) -> FetchResponse: ...


@dataclass(frozen=True, slots=True)
class FetchResponse:
    status_code: int
    content_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class _Event:
    period_label: str
    period_end: date | None
    record_date: date
    payment_date: date | None
    amount: float
    currency: str | None
    approval_date: date | None
    payment_year_label: str
    period_raw: str
    share_class: str


@dataclass(frozen=True, slots=True)
class _Loaded:
    fetch_status: FetchStatus
    http_status: int
    body: bytes
    events: tuple[_Event, ...]
    limitations: tuple[str, ...]


class HttpTransport:
    """One GET of the public IR workbook. No second client and no CCI path."""

    def __init__(self, timeout_s: float = 30.0) -> None:
        self._timeout_s = timeout_s

    def get(self, url: str) -> FetchResponse:
        try:
            with httpx.Client(timeout=self._timeout_s, follow_redirects=True, trust_env=False) as client:
                response = client.get(url)
        except httpx.HTTPError as exc:
            return FetchResponse(0, "", str(exc).encode("utf-8"))
        content_type = response.headers.get("content-type", "")
        return FetchResponse(response.status_code, content_type, response.content)


def content_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _hit_archive_cap(available: int, emitted: int) -> bool:
    return available > EVENT_CAP and emitted == EVENT_CAP


def _cap(limit: int) -> int:
    if limit < 0:
        return 0
    return min(limit, EVENT_CAP)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _period_end(kind: str, year: int) -> date | None:
    if kind == "FY":
        return date(year, 12, 31)
    if kind == "M9":
        return date(year, 9, 30)
    if kind == "H1":
        return date(year, 6, 30)
    if kind == "Q1":
        return date(year, 3, 31)
    return None


def _header_text(cell: object) -> str:
    return _clean_text(cell).lower().replace("ё", "е")


def _payment_column(header: tuple[object, ...]) -> int | None:
    for index, cell in enumerate(header):
        text = _header_text(cell)
        if any(marker in text for marker in _PAYMENT_HEADER_MARKERS):
            return index
    return None


def _currency(header: tuple[object, ...]) -> str | None:
    for cell in header:
        if "руб" in _header_text(cell):
            return "RUB"
    return None


def _same_row(raw: tuple[object, ...], parsed: dict[str, object]) -> bool:
    year_raw = _clean_text(raw[0] if raw else None)
    period_raw = _clean_text(raw[1] if len(raw) > 1 else None)
    amount, _share = parse_lukoil_amount(raw[2] if len(raw) > 2 else None)
    record = parse_russian_date(raw[4] if len(raw) > 4 else None)
    return (
        year_raw == parsed.get("year_raw")
        and period_raw == parsed.get("period_raw")
        and amount == parsed.get("amount_per_share")
        and record == parsed.get("record_date")
    )


def _payment_for(raw: tuple[object, ...], column: int | None) -> date | None:
    if column is None or len(raw) <= column:
        return None
    return parse_russian_date(raw[column])


def _events_from_workbook(payload: bytes) -> tuple[tuple[_Event, ...], tuple[str, ...]]:
    try:
        parsed = parse_lukoil_declared_sheet(payload, expected_share_class="common")
        sheet = _sheet_rows(payload)
    except _WORKBOOK_ERRORS:
        return (), ("workbook_unreadable",)
    header = tuple(sheet[0]) if sheet else ()
    currency = _currency(header)
    column = _payment_column(header)
    notes: list[str] = []
    if column is None:
        notes.append("payment_date_column_absent")
    attached: list[dict[str, object]] = []
    pending = list(parsed)
    current = pending.pop(0) if pending else None
    for raw in sheet[1:]:
        if current is None:
            break
        row = tuple(raw)
        if not _same_row(row, current):
            continue
        current["payment_date"] = _payment_for(row, column)
        attached.append(current)
        current = pending.pop(0) if pending else None
    if len(attached) != len(parsed):
        notes.append("payment_column_unaligned")
        attached = [{**row, "payment_date": None} for row in parsed]
    events: list[_Event] = []
    for row in attached:
        amount = row.get("amount_per_share")
        record = row.get("record_date")
        if not isinstance(amount, int | float) or isinstance(amount, bool) or amount <= 0:
            continue
        if not isinstance(record, date):
            continue
        key = row["period_key"]
        kind = str(getattr(key, "kind", ""))
        year = int(getattr(key, "year", 0))
        approval = row.get("shareholder_approval_date")
        payment = row.get("payment_date")
        events.append(
            _Event(
                period_label=f"{kind}:{year}",
                period_end=_period_end(kind, year),
                record_date=record,
                payment_date=payment if isinstance(payment, date) else None,
                amount=float(amount),
                currency=currency,
                approval_date=approval if isinstance(approval, date) else None,
                payment_year_label=str(row.get("year_raw") or ""),
                period_raw=str(row.get("period_raw") or ""),
                share_class=str(row.get("share_class") or "common"),
            )
        )
    return tuple(events), tuple(notes)


def _is_pdf(body: bytes, content_type: str) -> bool:
    if "pdf" in content_type.lower():
        return True
    return body.lstrip().startswith(b"%PDF")


def _is_html(body: bytes, content_type: str) -> bool:
    if "html" in content_type.lower():
        return True
    head = body.lstrip()[:800].lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html") or b"<html" in head


def _classify(response: FetchResponse) -> tuple[FetchStatus, tuple[str, ...]] | None:
    if response.status_code == 0:
        return FetchStatus.FAILED, ("transport_error",)
    if response.status_code in {401, 403} or _antibot(response.content):
        return FetchStatus.FORBIDDEN, ("issuer_ir_antibot_or_forbidden",)
    if response.status_code == 429:
        return FetchStatus.RATE_LIMITED, ("rate_limited",)
    if response.status_code >= 400:
        return FetchStatus.FAILED, (f"http_{response.status_code}",)
    if _is_pdf(response.content, response.content_type):
        return FetchStatus.UNSUPPORTED, ("pdf_not_parsed",)
    if _is_html(response.content, response.content_type):
        return FetchStatus.UNSUPPORTED, ("html_not_a_dividend_workbook",)
    if not response.content.startswith(b"PK"):
        return FetchStatus.FAILED, ("not_an_xlsx_workbook",)
    return None


def _antibot(body: bytes) -> bool:
    lowered = body.lower()
    if b"forbidden" not in lowered and b"captcha" not in lowered and b"access denied" not in lowered:
        return False
    markers = (b"request-id", b"request-ip", b"captcha", b"servicepipe", b"qrator")
    return any(marker in lowered for marker in markers)


def _external_id(event: _Event) -> str:
    payment = event.payment_date.isoformat() if event.payment_date else "na"
    return f"LKOH:{event.period_label}:{event.record_date.isoformat()}:{event.amount:.4f}:{payment}"


def _event_limitations(event: _Event, *, truncated: bool) -> tuple[str, ...]:
    notes = ["record_date_is_not_publication", "payment_year_label_is_not_a_date"]
    if event.payment_date is None:
        notes.append("payment_date_absent")
    else:
        notes.append("payment_date_from_explicit_column")
    if event.approval_date is None:
        notes.append("publication_timestamp_absent")
    else:
        notes.append("agm_date_in_period_text_not_used_as_published_at")
    if event.period_end is None:
        notes.append("period_end_unknown")
    else:
        notes.append("period_end_from_results_period_label")
    if truncated:
        notes.append("sample_capped_at_30")
    return tuple(notes)


class IssuerDividendsSource:
    """HistoricalSource for a capped Lukoil IR dividend archive."""

    source_id = SOURCE_ID

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or HttpTransport()
        self._clock = clock or (lambda: datetime.now(UTC))

    def discover(self) -> CoverageReport:
        return self.inspect_coverage()

    def inspect_coverage(self) -> CoverageReport:
        loaded = self._load()
        emitted = loaded.events[:EVENT_CAP]
        dated = [event.record_date for event in emitted]
        status = _adapter_status(loaded, emitted)
        limitations = _coverage_limitations(loaded, emitted)
        return CoverageReport(
            source_id=self.source_id,
            status=status,
            earliest=min(dated) if dated else None,
            latest=max(dated) if dated else None,
            formats=("xlsx",),
            limitations=limitations,
        )

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        loaded = self._load()
        if loaded.fetch_status != FetchStatus.OK:
            return (_blocked_artifact(loaded, observed_at=_aware(self._clock())),)
        budget = _cap(limit)
        chosen = loaded.events[:budget]
        return _artifacts(
            loaded,
            chosen,
            observed_at=_aware(self._clock()),
            truncated=_hit_archive_cap(len(loaded.events), len(chosen)),
        )

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        loaded = self._load()
        if loaded.fetch_status != FetchStatus.OK:
            return ()
        selected = [event for event in loaded.events if start <= event.record_date <= end]
        budget = _cap(limit)
        chosen = selected[:budget]
        return _artifacts(
            loaded,
            chosen,
            observed_at=_aware(self._clock()),
            truncated=_hit_archive_cap(len(selected), len(chosen)),
        )

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if artifact.fetch_status != FetchStatus.OK or artifact.source_id != SOURCE_ID:
            return ()
        events, _notes = _events_from_workbook(raw)
        matched = [event for event in events if _external_id(event) == artifact.external_document_id]
        return tuple(_observation(artifact, event) for event in matched)

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        checked: list[ParsedObservation] = []
        for observation in observations:
            errors = observation.quality_errors()
            if errors and observation.quality_status == RecordQuality.ACCEPTED:
                checked.append(
                    replace(
                        observation,
                        quality_status=RecordQuality.QUARANTINE,
                        limitations=observation.limitations + errors,
                    )
                )
            else:
                checked.append(observation)
        return tuple(checked)

    def _load(self) -> _Loaded:
        response = self._transport.get(SOURCE_URL)
        blocked = _classify(response)
        if blocked is not None:
            status, notes = blocked
            return _Loaded(status, response.status_code, response.content, (), notes)
        events, notes = _events_from_workbook(response.content)
        if notes == ("workbook_unreadable",):
            return _Loaded(FetchStatus.FAILED, response.status_code, response.content, (), notes)
        if not events:
            return _Loaded(
                FetchStatus.EMPTY,
                response.status_code,
                response.content,
                (),
                notes + ("amount_absent",),
            )
        return _Loaded(FetchStatus.OK, response.status_code, response.content, events, notes)


def _adapter_status(loaded: _Loaded, emitted: tuple[_Event, ...]) -> AdapterStatus:
    if emitted:
        return AdapterStatus.PARTIAL
    if loaded.fetch_status == FetchStatus.EMPTY:
        return AdapterStatus.PARTIAL
    if loaded.fetch_status == FetchStatus.FAILED:
        return AdapterStatus.FAILED
    return AdapterStatus.BLOCKED


def _coverage_limitations(loaded: _Loaded, emitted: tuple[_Event, ...]) -> tuple[str, ...]:
    notes = list(loaded.limitations)
    notes.append(f"http_status:{loaded.http_status}")
    notes.append(f"declared_rows_in_workbook:{len(loaded.events)}")
    notes.append(f"events_emitted:{min(len(loaded.events), EVENT_CAP)}")
    if len(loaded.events) > EVENT_CAP:
        notes.append("sample_capped_at_30")
    if emitted and all(event.payment_date is None for event in emitted):
        notes.append("payment_date_absent")
    if not loaded.events:
        notes.append("zero_invented_amounts")
    notes.append("pit:RESEARCH_ONLY")
    notes.append("publication_timestamp_absent")
    return tuple(dict.fromkeys(notes))


def _blocked_artifact(loaded: _Loaded, *, observed_at: datetime) -> HistoricalArtifact:
    return HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=SOURCE_URL,
        external_document_id="LKOH:blocked",
        document_type="issuer_dividend_xlsx",
        content_hash=content_hash(loaded.body),
        parser_version=PARSER_VERSION,
        fetch_status=loaded.fetch_status,
        first_observed_at=observed_at,
        title="LKOH issuer dividend archive",
        entity_identifiers={"secid": SECID},
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        quality_status=RecordQuality.UNRESOLVED,
        limitations=loaded.limitations + ("zero_invented_amounts",),
    )


def _artifacts(
    loaded: _Loaded,
    events: list[_Event] | tuple[_Event, ...],
    *,
    observed_at: datetime,
    truncated: bool,
) -> tuple[HistoricalArtifact, ...]:
    body_hash = content_hash(loaded.body)
    built: list[HistoricalArtifact] = []
    for event in events:
        built.append(
            HistoricalArtifact(
                source_id=SOURCE_ID,
                source_url=SOURCE_URL,
                external_document_id=_external_id(event),
                document_type="issuer_dividend_xlsx",
                content_hash=body_hash,
                parser_version=PARSER_VERSION,
                fetch_status=FetchStatus.OK,
                first_observed_at=observed_at,
                title=f"LKOH {event.period_label} dividend",
                entity_identifiers={"secid": SECID, "share_class": event.share_class},
                reporting_period=event.period_label,
                period_end=event.period_end,
                event_date=event.record_date,
                published_at=None,
                published_at_precision=PublishedAtPrecision.UNKNOWN,
                historical_availability_evidence=None,
                historical_pit_quality=PitQuality.RESEARCH_ONLY,
                quality_status=RecordQuality.ACCEPTED,
                limitations=_event_limitations(event, truncated=truncated),
            )
        )
    return tuple(built)


def _observation(artifact: HistoricalArtifact, event: _Event) -> ParsedObservation:
    evidence = f"lukoil_declared_xlsx:{SECID}:{event.record_date.isoformat()}:{event.amount:.4f}"
    return ParsedObservation(
        metric_id=METRIC_ID,
        source_id=SOURCE_ID,
        content_hash=artifact.content_hash,
        normalization_version=NORMALIZATION_VERSION,
        quality_status=RecordQuality.ACCEPTED,
        value=event.amount,
        unit="per_share",
        currency=event.currency,
        period=event.period_label,
        period_end=event.period_end,
        reporting_standard=None,
        issuer_identity={"secid": SECID, "share_class": event.share_class},
        evidence=evidence,
        limitations=artifact.limitations,
        extra={
            "record_date": event.record_date.isoformat(),
            "payment_date": event.payment_date.isoformat() if event.payment_date else None,
            "shareholder_approval_date": event.approval_date.isoformat() if event.approval_date else None,
            "payment_year_label": event.payment_year_label,
            "results_period": event.period_raw,
            "period_end": event.period_end.isoformat() if event.period_end else None,
        },
    )
