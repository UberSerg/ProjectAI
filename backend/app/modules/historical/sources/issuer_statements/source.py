"""IR-01 IFRS lines and IR-07 RAS absence from one public issuer workbook.

The download client uses the same timeout, redirects, and ``trust_env`` as
``IssuerIrXlsxDividendProvider``. Labels are cleaned with that provider's
``_clean_text``. This is not the dividend workbook and it does not crawl an
IR site: one FileSystem document, one fiscal year-end column.

``period_end`` comes from the balance-sheet header date. Income and cash-flow
annual columns are the integer year of that same date. ``published_at`` stays
empty unless the workbook states a publication date. ``PIT_VERIFIED`` is not
assigned. Banks do not receive these industrial statement lines.
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from io import BytesIO
from typing import Any

import httpx
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import BANK_FI_SECIDS
from app.modules.fundamentals.infrastructure.issuer_ir_xlsx_dividend_provider import (
    IssuerIrXlsxDividendProvider,
    _clean_text,
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

SOURCE_IFRS = "IR-01"
SOURCE_RAS = "IR-07"
PARSER_VERSION = "issuer_ir_statements_v1"
NORMALIZATION_VERSION = "issuer_ifrs_databook_lines_v1"
PILOT_SECID = "LKOH"
PILOT_ISSUER = "ПАО «ЛУКОЙЛ»"
PILOT_URL = "https://lukoil.ru/FileSystem/9/581055.xlsx?dl=1"
PILOT_FILENAME = "Lukoil_Analyst_databook_4Q2021_rus.xlsx"
PILOT_SHA256 = "6ef1b2b46d19d0615b0fb7440f37c80c1bf25786fa318fda3469342d64ff66fe"
PILOT_HTTP_STATUS = 200
DOCUMENT_TYPE = "issuer_ifrs_analyst_databook_xlsx"

_SHEETS = ("Contents", "Balance Sheet", "Statement of Income", "Cash Flows")
_MILLION_RUB = "млн руб."

# Exact cleaned labels. The sales line includes excise and export duties, so it
# is not registered as REVENUE. No EBITDA, margins, or other ratios.
_LINES: tuple[tuple[str, str, str], ...] = (
    ("Balance Sheet", "Денежные средства и их эквиваленты", "ifrs.CASH_AND_EQUIVALENTS"),
    ("Balance Sheet", "Итого активы", "ifrs.TOTAL_ASSETS"),
    ("Balance Sheet", "Итого капитал", "ifrs.TOTAL_EQUITY"),
    (
        "Statement of Income",
        "Выручка от реализации (включая акцизы и экспортные пошлины)",
        "ifrs.SALES_INCLUDING_EXCISE_AND_EXPORT_DUTIES",
    ),
    ("Statement of Income", "Операционная прибыль", "ifrs.OPERATING_INCOME"),
    (
        "Statement of Income",
        "Чистая прибыль (убыток), относящаяся к акционерам ПАО «ЛУКОЙЛ»",
        "ifrs.NET_INCOME",
    ),
    (
        "Cash Flows",
        "Чистые денежные средства, полученные от операционной деятельности",
        "ifrs.OPERATING_CASH_FLOW",
    ),
)


@dataclass(frozen=True, slots=True)
class IssuerStatementsResult:
    ir01_status: AdapterStatus
    ir07_status: AdapterStatus
    http_status: int | None
    http_status_source: str
    issuer: str
    secid: str
    source_url: str
    artifacts: tuple[HistoricalArtifact, ...]
    observations: tuple[ParsedObservation, ...]
    periods: tuple[str, ...]
    metrics: tuple[str, ...]
    fact_count: int
    ras_fact_count: int
    pit: tuple[str, ...]
    limitations: tuple[str, ...]
    blockers: tuple[str, ...]
    raw_by_document_id: dict[str, bytes] = field(default_factory=dict)


def chronology_problems(artifact: HistoricalArtifact) -> tuple[str, ...]:
    errors = list(artifact.chronology_errors())
    if artifact.period_end is not None and artifact.first_observed_at.date() == artifact.period_end:
        errors.append("period_end_equals_first_observed_at")
    if artifact.historical_pit_quality is PitQuality.PIT_VERIFIED:
        errors.append("pit_verified_without_statement_publication_evidence")
    return tuple(errors)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_xlsx(payload: bytes) -> bool:
    return payload.startswith(b"PK")


def _download(url: str, transport: httpx.BaseTransport | None) -> tuple[int, bytes]:
    """GET one URL. Client flags match ``IssuerIrXlsxDividendProvider._download``."""
    provider = IssuerIrXlsxDividendProvider()
    with httpx.Client(
        timeout=provider.timeout_s,
        follow_redirects=True,
        trust_env=provider.trust_env_proxy,
        transport=transport,
    ) as client:
        response = client.get(url)
        return response.status_code, response.content


def _load_sheets(payload: bytes) -> dict[str, list[tuple[Any, ...]]]:
    workbook = load_workbook(BytesIO(payload), data_only=True, read_only=True)
    try:
        loaded: dict[str, list[tuple[Any, ...]]] = {}
        for name in _SHEETS:
            if name not in workbook.sheetnames:
                continue
            sheet = workbook[name]
            loaded[name] = [tuple(row) for row in sheet.iter_rows(values_only=True)]
        return loaded
    finally:
        workbook.close()


def _labels(rows: list[tuple[Any, ...]]) -> dict[str, tuple[Any, ...]]:
    found: dict[str, tuple[Any, ...]] = {}
    for row in rows:
        if not row:
            continue
        label = _clean_text(row[0])
        if label and label not in found:
            found[label] = row
    return found


def _balance_header(rows: list[tuple[Any, ...]]) -> tuple[Any, ...] | None:
    for row in rows[:20]:
        if any(isinstance(cell, datetime) for cell in row):
            return row
    return None


def _flow_header(rows: list[tuple[Any, ...]]) -> tuple[Any, ...] | None:
    for row in rows[:20]:
        years = [cell for cell in row if isinstance(cell, int) and not isinstance(cell, bool) and 1990 <= cell <= 2100]
        if len(years) >= 2:
            return row
    return None


def _latest_year_end(header: tuple[Any, ...]) -> tuple[int, date] | None:
    found: list[tuple[int, date]] = []
    for index, cell in enumerate(header):
        if isinstance(cell, datetime):
            day = cell.date()
        elif isinstance(cell, date):
            day = cell
        else:
            continue
        if (day.month, day.day) == (12, 31):
            found.append((index, day))
    if not found:
        return None
    return max(found, key=lambda item: item[1])


def _year_index(header: tuple[Any, ...], year: int) -> int | None:
    for index, cell in enumerate(header):
        if isinstance(cell, int) and not isinstance(cell, bool) and cell == year:
            return index
    return None


def _number(row: tuple[Any, ...], index: int) -> float | None:
    if index >= len(row):
        return None
    value = row[index]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _unit(row: tuple[Any, ...]) -> tuple[str, str | None]:
    text = _clean_text(row[1] if len(row) > 1 else "")
    if text == _MILLION_RUB:
        return "million_rub", "RUB"
    if text:
        return text, None
    return "unlabeled", None


def _states_publication(sheets: Mapping[str, list[tuple[Any, ...]]]) -> bool:
    """True only when a cell states publication. The date itself is not guessed."""
    needles = ("дата публикации", "опубликован", "published at", "publication date")
    for rows in sheets.values():
        for row in rows[:25]:
            for cell in row[:6]:
                text = _clean_text(cell).lower()
                if any(needle in text for needle in needles):
                    return True
    return False


def _contents_standard(sheets: Mapping[str, list[tuple[Any, ...]]]) -> str:
    rows = sheets.get("Contents") or []
    text = " ".join(_clean_text(cell) for row in rows for cell in row[:4] if cell is not None)
    if "РСБУ" in text:
        return "RAS"
    if "МСФО" in text:
        return "IFRS"
    return "UNKNOWN"


def _empty(
    *,
    ir01: AdapterStatus,
    ir07: AdapterStatus,
    secid: str,
    url: str,
    http_status: int | None,
    http_status_source: str,
    limitations: tuple[str, ...],
    blockers: tuple[str, ...],
) -> IssuerStatementsResult:
    return IssuerStatementsResult(
        ir01_status=ir01,
        ir07_status=ir07,
        http_status=http_status,
        http_status_source=http_status_source,
        issuer=PILOT_ISSUER if secid == PILOT_SECID else secid,
        secid=secid,
        source_url=url,
        artifacts=(),
        observations=(),
        periods=(),
        metrics=(),
        fact_count=0,
        ras_fact_count=0,
        pit=(),
        limitations=limitations,
        blockers=blockers,
    )


class IssuerStatementsSource:
    """One Lukoil IFRS databook for IR-01. IR-07 stays empty when that file has no RAS."""

    source_id = SOURCE_IFRS

    def __init__(
        self,
        *,
        payload: bytes | None = None,
        transport: httpx.BaseTransport | None = None,
        secid: str = PILOT_SECID,
        observed_at: datetime | None = None,
        fixture_origin: str | None = None,
        url: str = PILOT_URL,
    ) -> None:
        self.payload = payload
        self.transport = transport
        self.secid = secid.upper()
        self.observed_at = observed_at or datetime.now(UTC)
        self.fixture_origin = fixture_origin
        self.url = url
        self._result: IssuerStatementsResult | None = None
        self._transport_error: str | None = None

    def run(self) -> IssuerStatementsResult:
        if self._result is None:
            self._result = self._execute()
        return self._result

    def discover(self) -> CoverageReport:
        result = self.run()
        ends = [item.period_end for item in result.artifacts if item.period_end is not None]
        return CoverageReport(
            source_id=self.source_id,
            status=result.ir01_status,
            earliest=min(ends) if ends else None,
            latest=max(ends) if ends else None,
            formats=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
            limitations=result.limitations,
        )

    def inspect_coverage(self) -> CoverageReport:
        return self.discover()

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        return self.run().artifacts[:limit]

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        selected = [
            item for item in self.run().artifacts if item.period_end is not None and start <= item.period_end <= end
        ]
        return tuple(selected[:limit])

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if artifact.document_type != DOCUMENT_TYPE or not _is_xlsx(raw):
            return ()
        try:
            parsed = _parse_ifrs(raw, secid=self.secid)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, InvalidFileException):
            return ()
        if parsed is None or parsed[2] != "IFRS":
            return ()
        observations = parsed[0]
        digest = _sha256(raw)
        if digest != artifact.content_hash:
            return tuple(_quarantine(item, "content_hash_mismatch") for item in observations)
        return observations

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        checked: list[ParsedObservation] = []
        for item in observations:
            if item.quality_errors():
                checked.append(_quarantine(item, None))
            else:
                checked.append(item)
        return tuple(checked)

    def _execute(self) -> IssuerStatementsResult:
        if self.observed_at.tzinfo is None:
            return _empty(
                ir01=AdapterStatus.FAILED,
                ir07=AdapterStatus.FAILED,
                secid=self.secid,
                url=self.url,
                http_status=None,
                http_status_source="not_requested",
                limitations=("first_observed_at_must_be_timezone_aware",),
                blockers=("first_observed_at_must_be_timezone_aware",),
            )
        if self.secid in BANK_FI_SECIDS:
            return _empty(
                ir01=AdapterStatus.BLOCKED,
                ir07=AdapterStatus.BLOCKED,
                secid=self.secid,
                url=self.url,
                http_status=None,
                http_status_source="not_requested",
                limitations=("BANK_FI_NOT_SUPPORTED", "industrial_statement_lines_not_emitted"),
                blockers=("BANK_FI_NOT_SUPPORTED",),
            )
        if self.secid != PILOT_SECID:
            return _empty(
                ir01=AdapterStatus.BLOCKED,
                ir07=AdapterStatus.BLOCKED,
                secid=self.secid,
                url=self.url,
                http_status=None,
                http_status_source="not_requested",
                limitations=("pilot_is_single_issuer", "no_second_document"),
                blockers=("pilot_is_single_issuer",),
            )

        http_status, http_status_source, payload = self._body()
        if http_status_source == "transport_error":
            name = getattr(self, "_transport_error", "HTTPError")
            return _empty(
                ir01=AdapterStatus.FAILED,
                ir07=AdapterStatus.FAILED,
                secid=self.secid,
                url=self.url,
                http_status=None,
                http_status_source=http_status_source,
                limitations=(name, "zero_invented_line_items"),
                blockers=(name,),
            )
        if payload is None:
            code = http_status if http_status is not None else 0
            return _empty(
                ir01=AdapterStatus.BLOCKED,
                ir07=AdapterStatus.BLOCKED,
                secid=self.secid,
                url=self.url,
                http_status=http_status,
                http_status_source=http_status_source,
                limitations=(f"http_{code}", "live_call_blocked"),
                blockers=(f"HTTP {code}",),
            )
        if not _is_xlsx(payload):
            return _empty(
                ir01=AdapterStatus.BLOCKED,
                ir07=AdapterStatus.BLOCKED,
                secid=self.secid,
                url=self.url,
                http_status=http_status,
                http_status_source=http_status_source,
                limitations=("response_is_not_xlsx", "zero_invented_line_items"),
                blockers=("response_is_not_xlsx",),
            )

        try:
            parsed = _parse_ifrs(payload, secid=self.secid)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, InvalidFileException) as exc:
            return _empty(
                ir01=AdapterStatus.BLOCKED,
                ir07=AdapterStatus.BLOCKED,
                secid=self.secid,
                url=self.url,
                http_status=http_status,
                http_status_source=http_status_source,
                limitations=(type(exc).__name__, "zero_invented_line_items"),
                blockers=("workbook_unreadable",),
            )
        if parsed is None:
            return _empty(
                ir01=AdapterStatus.BLOCKED,
                ir07=AdapterStatus.BLOCKED,
                secid=self.secid,
                url=self.url,
                http_status=http_status,
                http_status_source=http_status_source,
                limitations=("statement_period_header_absent", "zero_invented_line_items"),
                blockers=("statement_period_header_absent",),
            )
        observations, period_end, standard, publication_stated = parsed
        if standard != "IFRS":
            return _empty(
                ir01=AdapterStatus.BLOCKED,
                ir07=AdapterStatus.BLOCKED,
                secid=self.secid,
                url=self.url,
                http_status=http_status,
                http_status_source=http_status_source,
                limitations=("workbook_is_not_ifrs", "zero_invented_line_items", "ras_lines_not_invented"),
                blockers=("workbook_is_not_ifrs",),
            )
        if self.fixture_origin == "live_capture" and _sha256(payload) == PILOT_SHA256:
            http_status = PILOT_HTTP_STATUS
            http_status_source = "pilot_capture"
        digest = _sha256(payload)
        identity = {
            "secid": PILOT_SECID,
            "issuer_name": PILOT_ISSUER,
            "workbook": PILOT_FILENAME,
        }
        limitations = [
            "single_document_pilot",
            "analyst_databook_not_audited_financial_statements_pdf",
            (
                "publication_phrase_present_date_not_used_as_published_at"
                if publication_stated
                else "published_at_not_stated_in_workbook"
            ),
            "workbook_core_properties_are_not_publication_evidence",
            "secid_mapped_from_existing_ir_xlsx_catalog",
            "unit_million_rub_as_labeled",
            "no_ras_statement_in_document",
            "industrial_ifrs_lines_only",
            "sales_line_includes_excise_and_export_duties",
        ]
        if digest != PILOT_SHA256:
            limitations.append("workbook_sha256_differs_from_pilot_capture")
        artifact = HistoricalArtifact(
            source_id=SOURCE_IFRS,
            source_url=self.url,
            external_document_id="lukoil-filesystem-581055-fy2021",
            document_type=DOCUMENT_TYPE,
            content_hash=digest,
            parser_version=PARSER_VERSION,
            fetch_status=FetchStatus.OK,
            first_observed_at=self.observed_at,
            title=PILOT_FILENAME,
            entity_identifiers=identity,
            reporting_period=f"FY:{period_end.year}",
            period_end=period_end,
            published_at=None,
            published_at_precision=PublishedAtPrecision.UNKNOWN,
            historical_availability_evidence=None,
            historical_pit_quality=PitQuality.RESEARCH_ONLY,
            quality_status=RecordQuality.ACCEPTED,
            limitations=tuple(dict.fromkeys(limitations)),
        )
        problems = chronology_problems(artifact)
        if problems:
            artifact = _replace_artifact(artifact, RecordQuality.QUARANTINE, problems)
        bound = tuple(_bind(item, artifact) for item in observations)
        if problems:
            bound = tuple(_quarantine(item, None) for item in bound)
        metrics = tuple(item.metric_id for item in bound)
        notes = list(artifact.limitations)
        blockers: tuple[str, ...] = ()
        status = AdapterStatus.PARTIAL
        if not bound:
            blockers = ("no_allowlisted_lines",)
        elif problems:
            blockers = tuple(f"{artifact.external_document_id}:{error}" for error in problems)
        elif digest != PILOT_SHA256:
            blockers = ("workbook_sha256_differs_from_pilot_capture",)
        elif not _origin_can_claim_ready(self.fixture_origin, self.transport, self.payload, digest):
            status = AdapterStatus.PENDING
            mark = self.fixture_origin or "unmarked"
            notes.append(f"{mark}_fixture_cannot_claim_ready")
            blockers = (f"{mark}_fixture_cannot_claim_ready",)
        else:
            status = AdapterStatus.READY
        ras_blockers = ("ras_statement_absent_from_capped_document",)
        notes.extend(ras_blockers)
        return IssuerStatementsResult(
            ir01_status=status,
            ir07_status=AdapterStatus.BLOCKED,
            http_status=http_status,
            http_status_source=http_status_source,
            issuer=PILOT_ISSUER,
            secid=PILOT_SECID,
            source_url=self.url,
            artifacts=(artifact,),
            observations=bound,
            periods=(artifact.reporting_period or "",),
            metrics=metrics,
            fact_count=len(bound),
            ras_fact_count=0,
            pit=(artifact.historical_pit_quality.value,),
            limitations=tuple(dict.fromkeys(notes)),
            blockers=blockers,
            raw_by_document_id={artifact.external_document_id: payload},
        )

    def _body(self) -> tuple[int | None, str, bytes | None]:
        if self.payload is not None:
            return None, "not_requested", self.payload
        try:
            status, payload = _download(self.url, self.transport)
        except httpx.HTTPError as exc:
            self._transport_error = type(exc).__name__
            return None, "transport_error", None
        if status != 200:
            return status, "response", None
        return status, "response", payload


def _origin_can_claim_ready(
    origin: str | None,
    transport: httpx.BaseTransport | None,
    payload: bytes | None,
    digest: str,
) -> bool:
    if digest != PILOT_SHA256:
        return False
    if origin == "live_capture":
        return True
    if origin != "live_http" or payload is not None:
        return False
    return not isinstance(transport, httpx.MockTransport)


def _parse_ifrs(
    payload: bytes,
    *,
    secid: str,
) -> tuple[tuple[ParsedObservation, ...], date, str, bool] | None:
    if secid in BANK_FI_SECIDS:
        return None
    sheets = _load_sheets(payload)
    standard = _contents_standard(sheets)
    publication_stated = _states_publication(sheets)
    if standard != "IFRS":
        return ((), date.min, standard, publication_stated)
    balance_rows = sheets.get("Balance Sheet")
    if not balance_rows:
        return None
    header = _balance_header(balance_rows)
    if header is None:
        return None
    located = _latest_year_end(header)
    if located is None:
        return None
    column, period_end = located
    flow_columns: dict[str, int] = {}
    for name in ("Statement of Income", "Cash Flows"):
        rows = sheets.get(name)
        if not rows:
            return None
        flow_header = _flow_header(rows)
        if flow_header is None:
            return None
        index = _year_index(flow_header, period_end.year)
        if index is None:
            return None
        flow_columns[name] = index

    observations: list[ParsedObservation] = []
    for sheet_name, label, metric_id in _LINES:
        rows = sheets[sheet_name]
        row = _labels(rows).get(label)
        if row is None:
            continue
        index = column if sheet_name == "Balance Sheet" else flow_columns[sheet_name]
        value = _number(row, index)
        if value is None:
            continue
        unit, currency = _unit(row)
        limitations = ["explicit_zero"] if value == 0 else []
        if metric_id == "ifrs.SALES_INCLUDING_EXCISE_AND_EXPORT_DUTIES":
            limitations.append("not_canonical_revenue")
        if sheet_name == "Balance Sheet":
            limitations.append("period_end_from_balance_sheet_header_date")
        else:
            limitations.append("period_end_from_annual_year_column_aligned_to_balance_sheet")
        observations.append(
            ParsedObservation(
                metric_id=metric_id,
                source_id=SOURCE_IFRS,
                content_hash="",
                normalization_version=NORMALIZATION_VERSION,
                quality_status=RecordQuality.ACCEPTED,
                value=value,
                unit=unit,
                currency=currency,
                period=f"FY:{period_end.year}",
                period_end=period_end,
                reporting_standard="IFRS",
                issuer_identity={"secid": PILOT_SECID, "issuer_name": PILOT_ISSUER},
                evidence=label,
                limitations=tuple(limitations),
            )
        )
    return tuple(observations), period_end, standard, publication_stated


def _bind(item: ParsedObservation, artifact: HistoricalArtifact) -> ParsedObservation:
    return ParsedObservation(
        metric_id=item.metric_id,
        source_id=item.source_id,
        content_hash=artifact.content_hash,
        normalization_version=item.normalization_version,
        quality_status=artifact.quality_status,
        value=item.value,
        unit=item.unit,
        currency=item.currency,
        period=item.period,
        period_end=item.period_end,
        reporting_standard=item.reporting_standard,
        issuer_identity=dict(artifact.entity_identifiers),
        evidence=item.evidence,
        limitations=tuple(dict.fromkeys((*artifact.limitations, *item.limitations))),
        extra=dict(item.extra),
    )


def _quarantine(item: ParsedObservation, mark: str | None) -> ParsedObservation:
    limitations = item.limitations
    if mark and mark not in limitations:
        limitations = (*limitations, mark)
    return ParsedObservation(
        metric_id=item.metric_id,
        source_id=item.source_id,
        content_hash=item.content_hash,
        normalization_version=item.normalization_version,
        quality_status=RecordQuality.QUARANTINE,
        value=item.value,
        unit=item.unit,
        currency=item.currency,
        period=item.period,
        period_end=item.period_end,
        reporting_standard=item.reporting_standard,
        issuer_identity=dict(item.issuer_identity),
        evidence=item.evidence,
        limitations=limitations,
        extra=dict(item.extra),
    )


def _replace_artifact(
    artifact: HistoricalArtifact,
    quality: RecordQuality,
    problems: tuple[str, ...],
) -> HistoricalArtifact:
    return HistoricalArtifact(
        source_id=artifact.source_id,
        source_url=artifact.source_url,
        external_document_id=artifact.external_document_id,
        document_type=artifact.document_type,
        content_hash=artifact.content_hash,
        parser_version=artifact.parser_version,
        fetch_status=artifact.fetch_status,
        first_observed_at=artifact.first_observed_at,
        title=artifact.title,
        entity_identifiers=dict(artifact.entity_identifiers),
        reporting_period=artifact.reporting_period,
        period_end=artifact.period_end,
        event_date=artifact.event_date,
        published_at=artifact.published_at,
        published_at_precision=artifact.published_at_precision,
        historical_availability_evidence=artifact.historical_availability_evidence,
        historical_pit_quality=artifact.historical_pit_quality,
        revision_identifier=artifact.revision_identifier,
        raw_artifact_reference=artifact.raw_artifact_reference,
        quality_status=quality,
        limitations=tuple(dict.fromkeys((*artifact.limitations, *problems))),
    )
