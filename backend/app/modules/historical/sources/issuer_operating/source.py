"""Access check for one public issuer operating page.

IR-03 is the only task this page can support: a small HTML table titled
«Операционные показатели». RAS statements, press releases, and board or
shareholder decisions are not claimed from navigation labels or from an
unlabeled financial KPI table.

No anti-bot bypass, no XLSX download, no stage-1000 backfill, no decision-memory
writes. A missing publication time stays RESEARCH_ONLY.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Protocol

import httpx

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

SOURCE_ID = "IR-03"
PARSER_VERSION = "issuer_operating_access_v1"
NORMALIZATION_VERSION = "issuer_operating_table_v1"
ROW_CAP = 24
PAGE_URL = "https://www.magnit.com/ru/shareholders-and-investors/key-figures/"
USER_AGENT = "ProjectAI-historical-access-check/1.0 (research; one issuer)"

_UNCLAIMED = ("IR-02", "IR-04", "IR-06")
_YEAR_RE = re.compile(r"20\d{2}\Z")
_NUMBER_RE = re.compile(r"-?\d{1,3}(?: \d{3})*(?:,\d+)?\Z|-?\d+(?:,\d+)?\Z")
_LEGAL_NAME_RE = re.compile(r"(ПАО\s+[«\"][^»\"]+[»\"])")
_METRIC_SLUGS = {
    "количество магазинов": "store_count",
    "торговая площадь, тыс кв.м.": "selling_area_thousand_sqm",
    "количество населенных пунктов": "settlement_count",
    "количество чеков, млн": "receipts_million",
    "количество сотрудников, тыс. чел.": "employees_thousand",
}


class Transport(Protocol):
    def get(self, url: str) -> FetchResponse: ...


@dataclass(frozen=True, slots=True)
class FetchResponse:
    status_code: int
    content_type: str
    content: bytes
    url: str


@dataclass(frozen=True, slots=True)
class TaskCheck:
    task_id: str
    claimed: bool
    distinguished: bool
    status: AdapterStatus | None
    http_status: int | None
    rows: int | None
    pit: PitQuality | None
    reason: str


@dataclass(frozen=True, slots=True)
class OperatingAccessResult:
    artifact: HistoricalArtifact
    observations: tuple[ParsedObservation, ...]
    checks: tuple[TaskCheck, ...]
    table_rows: int


@dataclass(frozen=True, slots=True)
class _DataRow:
    cells: tuple[str, ...]
    conflict: bool


@dataclass(frozen=True, slots=True)
class _Table:
    heading: str
    columns: tuple[str, ...]
    rows: tuple[_DataRow, ...]


@dataclass(frozen=True, slots=True)
class _ParsedPage:
    title: str
    headings: tuple[str, ...]
    tables: tuple[_Table, ...]
    binary_links: tuple[str, ...]


def fixture_bytes(name: str) -> bytes:
    from pathlib import Path

    return (Path(__file__).resolve().parent / "fixtures" / name).read_bytes()


def content_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class HttpTransport:
    """Single direct GET. Redirects are followed. Challenges are not solved."""

    def get(self, url: str) -> FetchResponse:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,text/csv;q=0.9,*/*;q=0.8"}
        with httpx.Client(timeout=25.0, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
        return FetchResponse(
            status_code=response.status_code,
            content_type=response.headers.get("content-type", ""),
            content=response.content,
            url=str(response.url),
        )


class IssuerOperatingSource:
    """HistoricalSource for a bounded public operating-table access check."""

    source_id = SOURCE_ID

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        clock: Callable[[], datetime] | None = None,
        page_url: str = PAGE_URL,
    ) -> None:
        self._transport = transport or HttpTransport()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._page_url = page_url

    def discover(self) -> CoverageReport:
        return self.inspect_coverage()

    def inspect_coverage(self) -> CoverageReport:
        result = self.access_check(limit=ROW_CAP)
        return CoverageReport(
            source_id=self.source_id,
            status=result.checks[0].status or AdapterStatus.BLOCKED,
            earliest=None,
            latest=None,
            formats=("html", "csv"),
            limitations=result.artifact.limitations,
        )

    def fetch_sample(self, *, limit: int = ROW_CAP) -> tuple[HistoricalArtifact, ...]:
        return (self.access_check(limit=limit).artifact,)

    def fetch_range(
        self, *, start: date, end: date, limit: int
    ) -> tuple[HistoricalArtifact, ...]:
        del start, end
        result = self.access_check(limit=limit)
        artifact = result.artifact
        notes = artifact.limitations
        if "range_backfill_not_supported" not in notes:
            notes = (*notes, "range_backfill_not_supported")
        return (_replace_limitations(artifact, notes),)

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        status = _http_status_from_limitations(artifact.limitations)
        result = parse_operating_response(
            raw,
            http_status=status if status is not None else 200,
            content_type="",
            source_url=artifact.source_url,
            observed_at=artifact.first_observed_at,
            limit=ROW_CAP,
        )
        if status is not None and status >= 400:
            return ()
        return result.observations

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        checked: list[ParsedObservation] = []
        for item in observations:
            if item.quality_errors():
                checked.append(
                    ParsedObservation(
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
                        issuer_identity=item.issuer_identity,
                        evidence=item.evidence,
                        limitations=tuple(dict.fromkeys((*item.limitations, *item.quality_errors()))),
                        extra=item.extra,
                    )
                )
            else:
                checked.append(item)
        return tuple(checked)

    def access_check(self, *, limit: int = ROW_CAP) -> OperatingAccessResult:
        fetched = self._transport.get(self._page_url)
        observed_at = self._clock()
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        return parse_operating_response(
            fetched.content,
            http_status=fetched.status_code,
            content_type=fetched.content_type,
            source_url=fetched.url or self._page_url,
            observed_at=observed_at,
            limit=limit,
        )


def parse_operating_response(
    body: bytes,
    *,
    http_status: int,
    content_type: str,
    source_url: str,
    observed_at: datetime,
    limit: int,
) -> OperatingAccessResult:
    row_budget = _row_budget(limit)
    blocked = http_status >= 400 or _is_gateway_block(body)
    kind = "blocked" if blocked else _body_kind(body, content_type)
    page = _ParsedPage("", (), (), ())
    operating_rows: tuple[_DataRow, ...] = ()
    columns: tuple[str, ...] = ()
    heading = ""
    if not blocked and kind == "html":
        page = _parse_html(body)
        table = _operating_table(page)
        if table is not None:
            heading = table.heading
            columns = table.columns
            operating_rows = table.rows
    elif not blocked and kind == "csv":
        columns, operating_rows = _parse_csv(body)
        heading = "csv"
        page = _ParsedPage("", ("csv",), (), ())
    kept = operating_rows[:row_budget]
    capped = len(operating_rows) > row_budget
    aligned = tuple(row for row in kept if not row.conflict)
    unaligned = tuple(row for row in kept if row.conflict)
    identity = _identity(page.title)
    observations = _observations(
        aligned,
        columns=columns,
        heading=heading,
        identity=identity,
        body=body,
        observed_at=observed_at,
    )
    if blocked:
        fetch_status = _blocked_fetch_status(http_status, body)
        adapter_status = AdapterStatus.BLOCKED
        document_type = "http_blocked"
    elif not kept:
        fetch_status = FetchStatus.EMPTY
        adapter_status = AdapterStatus.PARTIAL
        document_type = "issuer_operating_page"
    else:
        fetch_status = FetchStatus.OK
        adapter_status = AdapterStatus.PARTIAL
        document_type = "issuer_operating_html_table" if kind == "html" else "issuer_operating_csv_table"
    limitations = _limitations(
        http_status=http_status,
        blocked=blocked,
        capped=capped,
        binary_links=page.binary_links,
        kept=bool(aligned),
        kind=kind,
        unaligned=unaligned,
    )
    artifact = HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=source_url,
        external_document_id=f"operating:{content_hash(body)[:16]}",
        document_type=document_type,
        content_hash=content_hash(body),
        parser_version=PARSER_VERSION,
        fetch_status=fetch_status,
        first_observed_at=observed_at,
        title=page.title or None,
        entity_identifiers=identity,
        published_at=None,
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_availability_evidence=None,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        quality_status=RecordQuality.QUARANTINE if kept else RecordQuality.UNRESOLVED,
        limitations=limitations,
    )
    checks = _task_checks(
        page=page,
        http_status=http_status,
        adapter_status=adapter_status,
        rows=len(aligned) if not blocked else 0,
        blocked=blocked,
        kind=kind,
    )
    return OperatingAccessResult(
        artifact=artifact,
        observations=() if blocked else observations,
        checks=checks,
        table_rows=0 if blocked else len(aligned),
    )


def _replace_limitations(artifact: HistoricalArtifact, limitations: tuple[str, ...]) -> HistoricalArtifact:
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
        entity_identifiers=artifact.entity_identifiers,
        reporting_period=artifact.reporting_period,
        period_end=artifact.period_end,
        event_date=artifact.event_date,
        published_at=artifact.published_at,
        published_at_precision=artifact.published_at_precision,
        historical_availability_evidence=artifact.historical_availability_evidence,
        historical_pit_quality=artifact.historical_pit_quality,
        revision_identifier=artifact.revision_identifier,
        raw_artifact_reference=artifact.raw_artifact_reference,
        quality_status=artifact.quality_status,
        limitations=limitations,
    )


def _row_budget(limit: int) -> int:
    if limit < 1:
        return 0
    return min(limit, ROW_CAP)


def _blocked_fetch_status(http_status: int, body: bytes) -> FetchStatus:
    if http_status == 429:
        return FetchStatus.RATE_LIMITED
    if http_status in {401, 403} or _is_gateway_block(body):
        return FetchStatus.FORBIDDEN if http_status in {401, 403} else FetchStatus.UNSUPPORTED
    if http_status >= 400:
        return FetchStatus.FAILED
    return FetchStatus.UNSUPPORTED


def _is_gateway_block(body: bytes) -> bool:
    head = body[:8000].lower()
    if b"cf-browser-verification" in head or b"just a moment" in head:
        return True
    if b"id=\"request-id\"" in head and b"forbidden" in head:
        return True
    if b"<title>403" in head or b"<h1>403 forbidden</h1>" in head:
        return True
    return False


def _body_kind(body: bytes, content_type: str) -> str:
    lowered_type = content_type.lower()
    if "csv" in lowered_type:
        return "csv"
    if "spreadsheet" in lowered_type or "excel" in lowered_type or body[:2] == b"PK":
        return "xlsx"
    sample = body.lstrip().lstrip(b"\xef\xbb\xbf")
    head = sample[:200].lower()
    if head.startswith(b"<") or b"<html" in head or b"<z-table" in sample[:4000].lower():
        return "html"
    if b"<z-table" in sample.lower() or b"<table" in sample.lower():
        return "html"
    if sample and b"\n" in sample and b"<" not in sample[:200]:
        return "csv"
    return "other"


def _limitations(
    *,
    http_status: int,
    blocked: bool,
    capped: bool,
    binary_links: tuple[str, ...],
    kept: bool,
    kind: str,
    unaligned: tuple[_DataRow, ...] = (),
) -> tuple[str, ...]:
    notes = [f"http_status:{http_status}", "publication_timestamp_absent", "pit_research_only"]
    if blocked:
        notes.append("operating_figures_not_invented")
    if capped:
        notes.append("row_cap_24")
    if binary_links:
        notes.append("xlsx_or_pdf_link_not_fetched")
    if kind == "xlsx":
        notes.append("xlsx_is_not_an_html_or_csv_table")
    if not blocked and not kept and kind != "xlsx":
        notes.append("no_operating_table")
    if kept:
        notes.append("annual_key_figures_not_monthly_retail_sales")
        notes.append("not_a_production_series")
        notes.append("year_column_is_not_period_end")
    for row in unaligned:
        label = row.cells[0].strip() if row.cells else "row"
        notes.append(f"unaligned_operating_row:{label}")
    return tuple(dict.fromkeys(notes))


def _task_checks(
    *,
    page: _ParsedPage,
    http_status: int,
    adapter_status: AdapterStatus,
    rows: int,
    blocked: bool,
    kind: str,
) -> tuple[TaskCheck, ...]:
    headings = tuple(item.casefold().replace("ё", "е") for item in page.headings)
    distinguished = {
        "IR-02": any("рсбу" in item or re.search(r"\bras\b", item) for item in headings),
        "IR-04": any("пресс-релиз" in item or "press release" in item for item in headings),
        "IR-06": any(
            "совет директоров" in item or "собрание акционеров" in item or "решение акционер" in item
            for item in headings
        ),
    }
    if blocked:
        ir03_reason = "access check blocked; operating figures were not invented"
    elif rows:
        ir03_reason = "public operating HTML/CSV table parsed; publication time is absent"
    elif kind == "xlsx":
        ir03_reason = "response is not an HTML or CSV table; workbook was not parsed"
    else:
        ir03_reason = "page fetched; no operating table was distinguished"
    ir03 = TaskCheck(
        task_id="IR-03",
        claimed=True,
        distinguished=bool(rows) or any("операцион" in item and "финанс" not in item for item in headings),
        status=adapter_status,
        http_status=http_status,
        rows=rows,
        pit=PitQuality.RESEARCH_ONLY,
        reason=ir03_reason,
    )
    others = [
        TaskCheck(
            task_id=task_id,
            claimed=False,
            distinguished=distinguished[task_id],
            status=None,
            http_status=None,
            rows=None,
            pit=None,
            reason=_unclaimed_reason(task_id, distinguished[task_id]),
        )
        for task_id in _UNCLAIMED
    ]
    return (ir03, *others)


def _unclaimed_reason(task_id: str, distinguished: bool) -> str:
    if task_id == "IR-02" and distinguished:
        return "RAS heading is visible and was not parsed"
    if task_id == "IR-02":
        return "not distinguished: no RAS or РСБУ heading on the checked page"
    if task_id == "IR-04" and distinguished:
        return "press-release heading is visible and was not parsed"
    if task_id == "IR-04":
        return "not distinguished: no press-release heading on the checked page"
    if distinguished:
        return "board or shareholder heading is visible and was not parsed"
    return "not distinguished: no board or shareholder decision heading on the checked page"


def _identity(title: str) -> dict[str, str]:
    match = _LEGAL_NAME_RE.search(title)
    if match is None:
        return {}
    return {"legal_name": " ".join(match.group(1).split())}


def _observations(
    rows: tuple[_DataRow, ...],
    *,
    columns: tuple[str, ...],
    heading: str,
    identity: dict[str, str],
    body: bytes,
    observed_at: datetime,
) -> tuple[ParsedObservation, ...]:
    years = [column for column in columns[1:] if _YEAR_RE.fullmatch(column.strip())]
    digest = content_hash(body)
    found: list[ParsedObservation] = []
    for row_index, row in enumerate(rows):
        if row.conflict or not row.cells:
            continue
        label = row.cells[0].strip()
        if not label:
            continue
        values = row.cells[1:]
        pairs = list(zip(years, values, strict=False))
        if not years:
            pairs = [(f"col_{index + 1}", value) for index, value in enumerate(values)]
        for period, raw_value in pairs:
            parsed = _parse_number(raw_value)
            limitations = [
                "publication_timestamp_absent",
                "year_column_is_not_period_end",
                "not_monthly_operating_series",
            ]
            if parsed == 0:
                limitations.append("explicit_zero")
            slug = _METRIC_SLUGS.get(_fold(label), f"row_{row_index}")
            found.append(
                ParsedObservation(
                    metric_id=f"issuer.operating.{slug}",
                    source_id=SOURCE_ID,
                    content_hash=digest,
                    normalization_version=NORMALIZATION_VERSION,
                    quality_status=RecordQuality.QUARANTINE if parsed is not None else RecordQuality.UNRESOLVED,
                    value=parsed,
                    unit=_unit(label),
                    currency=None,
                    period=period,
                    period_end=None,
                    reporting_standard=None,
                    issuer_identity=identity,
                    evidence=f"{heading} | {label} | {period} | {raw_value.strip()}",
                    limitations=tuple(limitations),
                    extra={"label": label, "observed_at": observed_at.isoformat()},
                )
            )
    return tuple(found)


def _operating_table(page: _ParsedPage) -> _Table | None:
    for table in page.tables:
        folded = _fold(table.heading)
        if "операцион" in folded and "финанс" not in folded:
            return table
    return None


def _fold(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split())


def _unit(label: str) -> str:
    folded = _fold(label)
    if "тыс кв" in folded:
        return "thousand_sqm"
    if "млн" in folded:
        return "million"
    if "тыс" in folded:
        return "thousand"
    return "count"


def _parse_number(raw: str) -> float | None:
    text = raw.replace("\xa0", " ").replace("\u202f", " ").strip()
    if not _NUMBER_RE.fullmatch(text):
        return None
    return float(text.replace(" ", "").replace(",", "."))


def _parse_columns(raw: str) -> tuple[str, ...]:
    text = raw.strip()
    if not text:
        return ()
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return ()
    if isinstance(value, list | tuple):
        return tuple(str(item).strip() for item in value)
    return ()


def _parse_csv(body: bytes) -> tuple[tuple[str, ...], tuple[_DataRow, ...]]:
    text = body.decode("utf-8-sig", errors="replace")
    sample = text.splitlines()[0] if text.splitlines() else ""
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    records = [tuple(cell.strip() for cell in row) for row in reader if any(cell.strip() for cell in row)]
    if not records:
        return (), ()
    return records[0], tuple(_DataRow(cells=row, conflict=False) for row in records[1:])


class _HtmlTables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._capture_heading = False
        self.heading = ""
        self.headings: list[str] = []
        self._heading_parts: list[str] = []
        self.tables: list[_Table] = []
        self._columns: tuple[str, ...] = ()
        self._rows: list[_DataRow] = []
        self._in_table = 0
        self._row_slots: dict[int, str] | None = None
        self._row_conflict = False
        self._cell: list[str] | None = None
        self._cell_index: int | None = None
        self._next_index = 0
        self.binary_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        if low in {"script", "style", "noscript"}:
            self._skip += 1
            return
        if self._skip:
            return
        attr = {key.lower(): value or "" for key, value in attrs}
        if low == "title":
            self._in_title = True
            self._title_parts = []
        if low in {"h1", "h2", "h3", "h4"}:
            self._capture_heading = True
            self._heading_parts = []
        if low in {"a", "z-link"}:
            href = attr.get("href", "")
            if href.lower().split("?", 1)[0].endswith((".xlsx", ".xls", ".pdf")):
                self.binary_links.append(href)
        if low in {"table", "z-table"}:
            self._in_table += 1
            if self._in_table == 1:
                self._columns = _parse_columns(attr.get(":columns") or attr.get("columns") or "")
                self._rows = []
        if low in {"tr", "z-table-row"} and self._in_table:
            self._row_slots = {}
            self._row_conflict = False
            self._next_index = 0
        if low in {"td", "th", "z-table-col"} and self._row_slots is not None:
            self._cell = []
            raw_index = attr.get("index", "")
            if raw_index.isdigit():
                self._cell_index = int(raw_index)
            else:
                self._cell_index = self._next_index
                self._next_index += 1

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return
        if low == "title":
            self._in_title = False
        if low in {"h1", "h2", "h3", "h4"} and self._capture_heading:
            text = " ".join("".join(self._heading_parts).split())
            self._capture_heading = False
            self._heading_parts = []
            if text:
                self.heading = text
                self.headings.append(text)
        if low in {"td", "th", "z-table-col"} and self._cell is not None and self._row_slots is not None:
            text = " ".join("".join(self._cell).split())
            index = self._cell_index if self._cell_index is not None else len(self._row_slots)
            if index in self._row_slots:
                self._row_conflict = True
            self._row_slots[index] = text
            self._cell = None
            self._cell_index = None
        if low in {"tr", "z-table-row"} and self._row_slots is not None:
            if any(self._row_slots.values()):
                width = max(self._row_slots) + 1
                cells = tuple(self._row_slots.get(index, "") for index in range(width))
                self._rows.append(_DataRow(cells=cells, conflict=self._row_conflict))
            self._row_slots = None
            self._row_conflict = False
        if low in {"table", "z-table"} and self._in_table:
            self._in_table -= 1
            if self._in_table == 0:
                self.tables.append(_Table(self.heading, self._columns, tuple(self._rows)))
                self._rows = []
                self._columns = ()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self._title_parts.append(data)
        if self._capture_heading:
            self._heading_parts.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def page(self) -> _ParsedPage:
        title = " ".join("".join(self._title_parts).split())
        return _ParsedPage(title, tuple(self.headings), tuple(self.tables), tuple(dict.fromkeys(self.binary_links)))


def _parse_html(body: bytes) -> _ParsedPage:
    parser = _HtmlTables()
    parser.feed(body.decode("utf-8", errors="replace"))
    return parser.page()


def _http_status_from_limitations(limitations: tuple[str, ...]) -> int | None:
    for item in limitations:
        if item.startswith("http_status:"):
            raw = item.split(":", 1)[1]
            if raw.isdigit():
                return int(raw)
    return None
