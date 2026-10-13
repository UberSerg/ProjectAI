"""Offline access check for the Magnit operating table.

Live HTTP is not called. probe_note.json records the 2026-10-13 response.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.issuer_operating.source import (
    ROW_CAP,
    FetchResponse,
    IssuerOperatingSource,
    fixture_bytes,
    parse_operating_response,
)

CLOCK = datetime(2026, 10, 13, 5, 40, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parents[3] / "app" / "modules" / "historical" / "sources" / "issuer_operating"
SOURCE_PATH = FIXTURES / "source.py"
PROBE_PATH = FIXTURES / "fixtures" / "probe_note.json"


class MapTransport:
    def __init__(self, response: FetchResponse) -> None:
        self.response = response
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResponse:
        self.calls.append(url)
        return self.response


def _source(
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "text/html; charset=UTF-8",
) -> tuple[IssuerOperatingSource, MapTransport]:
    transport = MapTransport(
        FetchResponse(
            status_code=status,
            content_type=content_type,
            content=body,
            url="https://www.magnit.com/ru/shareholders-and-investors/key-figures/",
        )
    )
    return IssuerOperatingSource(transport=transport, clock=lambda: CLOCK), transport


def _operating_html(row_count: int) -> bytes:
    rows = []
    for index in range(row_count):
        rows.append(
            "<z-table-row>"
            f"<z-table-col index=\"0\">Метрика {index}</z-table-col>"
            f"<z-table-col index=\"1\">{index + 1}</z-table-col>"
            "</z-table-row>"
        )
    html = (
        "<html><head><title>Ключевые показатели - ПАО «Магнит»</title></head><body>"
        "<h3>Операционные показатели</h3>"
        "<z-table :columns=\"['Показатель', '2024']\">"
        + "".join(rows)
        + "</z-table></body></html>"
    )
    return html.encode()


def test_magnit_operating_table_keeps_pit_unknown() -> None:
    body = fixture_bytes("magnit_key_figures.html")
    source, transport = _source(body)
    result = source.access_check()
    assert transport.calls == ["https://www.magnit.com/ru/shareholders-and-investors/key-figures/"]
    assert result.table_rows == 4
    assert len(result.observations) == 20
    artifact = result.artifact
    assert artifact.fetch_status is FetchStatus.OK
    assert artifact.published_at is None
    assert artifact.published_at_precision is PublishedAtPrecision.UNKNOWN
    assert artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert artifact.historical_availability_evidence is None
    assert artifact.period_end is None
    assert artifact.first_observed_at == CLOCK
    assert artifact.chronology_errors() == ()
    assert artifact.entity_identifiers == {"legal_name": "ПАО «Магнит»"}
    assert "MGNT" not in artifact.entity_identifiers
    stores_2024 = next(
        item
        for item in result.observations
        if item.extra["label"] == "Количество магазинов" and item.period == "2024"
    )
    assert stores_2024.value == 31482
    assert stores_2024.unit == "count"
    assert stores_2024.period_end is None
    assert stores_2024.quality_status is RecordQuality.QUARANTINE
    assert stores_2024.quality_errors() == ()
    assert result.checks[0].task_id == "IR-03"
    assert result.checks[0].claimed is True
    assert result.checks[0].distinguished is True
    assert result.checks[0].status is AdapterStatus.PARTIAL
    assert result.checks[0].rows == 4
    assert result.checks[0].pit is PitQuality.RESEARCH_ONLY
    coverage = source.inspect_coverage()
    assert coverage.status is AdapterStatus.PARTIAL
    assert coverage.earliest is None
    assert coverage.latest is None


def test_financial_table_xlsx_and_nav_links_do_not_become_operating_facts() -> None:
    body = fixture_bytes("magnit_key_figures.html")
    result = parse_operating_response(
        body,
        http_status=200,
        content_type="text/html",
        source_url="https://www.magnit.com/ru/shareholders-and-investors/key-figures/",
        observed_at=CLOCK,
        limit=ROW_CAP,
    )
    values = {item.value for item in result.observations}
    assert 1856 not in values
    assert 3509 not in values
    labels = {item.extra["label"] for item in result.observations}
    assert "Выручка, млрд руб." not in labels
    assert "Количество сотрудников, тыс. чел." not in labels
    assert 368 not in values
    assert 394 not in values
    assert any(item.startswith("unaligned_operating_row:") for item in result.artifact.limitations)
    assert "xlsx_or_pdf_link_not_fetched" in result.artifact.limitations
    by_id = {item.task_id: item for item in result.checks}
    assert by_id["IR-02"].claimed is False
    assert by_id["IR-02"].distinguished is False
    assert by_id["IR-04"].claimed is False
    assert by_id["IR-04"].distinguished is False
    assert by_id["IR-06"].claimed is False
    assert by_id["IR-06"].distinguished is False
    parsed = IssuerOperatingSource(clock=lambda: CLOCK).parse(result.artifact, body)
    assert len(parsed) == 20
    assert all(item.period_end is None for item in parsed)


def test_ras_heading_is_distinguished_and_not_parsed_as_operating() -> None:
    body = """<html><head><title>Отчет</title></head><body>
    <h3>Отчетность РСБУ</h3>
    <z-table :columns="['Показатель', '2024']">
      <z-table-row>
        <z-table-col index="0">Выручка</z-table-col>
        <z-table-col index="1">999</z-table-col>
      </z-table-row>
    </z-table>
    </body></html>""".encode()
    result = parse_operating_response(
        body,
        http_status=200,
        content_type="text/html",
        source_url="https://example.invalid/ras",
        observed_at=CLOCK,
        limit=ROW_CAP,
    )
    assert result.observations == ()
    assert result.table_rows == 0
    by_id = {item.task_id: item for item in result.checks}
    assert by_id["IR-02"].distinguished is True
    assert by_id["IR-02"].claimed is False
    assert by_id["IR-03"].rows == 0
    assert 999 not in {item.value for item in result.observations}


def test_forbidden_page_records_status_and_invents_nothing() -> None:
    body = fixture_bytes("magnit_files_403.html") + "Количество магазинов 26 077".encode()
    result = parse_operating_response(
        body,
        http_status=403,
        content_type="text/html",
        source_url="https://www.magnit.com/files/ru/shareholders-and-investors/",
        observed_at=CLOCK,
        limit=ROW_CAP,
    )
    assert result.observations == ()
    assert result.table_rows == 0
    assert result.artifact.fetch_status is FetchStatus.FORBIDDEN
    assert result.artifact.published_at is None
    assert result.artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert "http_status:403" in result.artifact.limitations
    assert "operating_figures_not_invented" in result.artifact.limitations
    assert result.checks[0].task_id == "IR-03"
    assert result.checks[0].status is AdapterStatus.BLOCKED
    assert result.checks[0].rows == 0
    assert all(item.claimed is False for item in result.checks if item.task_id != "IR-03")


def test_row_cap_stops_at_24_even_if_caller_asks_for_stage_1000() -> None:
    body = _operating_html(25)
    result = parse_operating_response(
        body,
        http_status=200,
        content_type="text/html",
        source_url="https://www.magnit.com/ru/shareholders-and-investors/key-figures/",
        observed_at=CLOCK,
        limit=1000,
    )
    assert result.table_rows == ROW_CAP
    assert len(result.observations) == ROW_CAP
    assert "row_cap_24" in result.artifact.limitations
    assert "Метрика 24" not in {item.extra["label"] for item in result.observations}
    source, transport = _source(body)
    ranged = source.fetch_range(start=date(2020, 1, 1), end=date(2025, 12, 31), limit=1000)
    assert len(transport.calls) == 1
    assert len(ranged) == 1
    assert "range_backfill_not_supported" in ranged[0].limitations


def test_csv_is_capped_and_xlsx_bytes_contribute_no_figures() -> None:
    csv_body = "metric,2024\n" + "\n".join(f"row{index},{index}" for index in range(30))
    csv_result = parse_operating_response(
        csv_body.encode(),
        http_status=200,
        content_type="text/csv",
        source_url="https://example.invalid/operating.csv",
        observed_at=CLOCK,
        limit=100,
    )
    assert csv_result.table_rows == 24
    assert csv_result.checks[0].claimed is True
    assert all(item.claimed is False for item in csv_result.checks[1:])
    xlsx = parse_operating_response(
        b"PK\x03\x04" + b"999999",
        http_status=200,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        source_url="https://www.magnit.com/upload/ru_files/shareholders-and-investors/key-figures-ru.xlsx",
        observed_at=CLOCK,
        limit=ROW_CAP,
    )
    assert xlsx.observations == ()
    assert xlsx.table_rows == 0
    assert "xlsx_is_not_an_html_or_csv_table" in xlsx.artifact.limitations
    assert 999999 not in {item.value for item in xlsx.observations}


def test_probe_note_matches_the_checked_task_only() -> None:
    probe = json.loads(PROBE_PATH.read_text(encoding="utf-8"))
    assert probe["http_status"] == 200
    assert probe["aligned_rows"] == 4
    assert probe["numeric_observations"] == 20
    assert probe["pit"] == "RESEARCH_ONLY"
    assert probe["published_at"] is None
    assert probe["tasks"]["IR-03"]["claimed"] is True
    assert probe["tasks"]["IR-03"]["rows"] == 4
    assert probe["tasks"]["IR-02"]["claimed"] is False
    assert probe["tasks"]["IR-04"]["claimed"] is False
    assert probe["tasks"]["IR-06"]["claimed"] is False
    assert probe["blocked_listing"]["http_status"] == 403
    assert probe["blocked_listing"]["operating_rows"] == 0
    body = fixture_bytes("magnit_key_figures.html")
    result = parse_operating_response(
        body,
        http_status=200,
        content_type="text/html",
        source_url=probe["url"],
        observed_at=CLOCK,
        limit=ROW_CAP,
    )
    assert result.table_rows == probe["aligned_rows"]
    assert len(result.observations) == probe["numeric_observations"]
    forbidden = fixture_bytes("magnit_files_403.html")
    assert len(forbidden) == probe["blocked_listing"]["bytes"]


def test_module_does_not_call_llm_or_write_prospective_memory() -> None:
    text = SOURCE_PATH.read_text(encoding="utf-8").lower()
    assert "prospective_captures" not in text
    assert "polza" not in text
    assert "openai" not in text
    assert "sqlalchemy" not in text
    assert "stage_1000" not in text
    assert "playwright" not in text
    assert "captcha" not in text
