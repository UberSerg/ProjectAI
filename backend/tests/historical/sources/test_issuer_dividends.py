"""Offline IR-05 tests. The Lukoil workbook fixture is a saved public file, not a live call."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    ParsedObservation,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.issuer_dividends.source import (
    EVENT_CAP,
    SOURCE_URL,
    FetchResponse,
    IssuerDividendsSource,
)

CLOCK = datetime(2026, 10, 13, 5, 0, tzinfo=UTC)
FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "modules"
    / "historical"
    / "sources"
    / "issuer_dividends"
    / "fixtures"
)
SOURCE_PATH = FIXTURES.parent / "source.py"
HEADER = (
    "ГОД ВЫПЛАТЫ ДИВИДЕНДОВ",
    "ПО РЕЗУЛЬТАТАМ ПЕРИОДА",
    "ДИВИДЕНД НА 1 АКЦИЮ (вид акции: обыкновенная/ привилегированная), РУБ.",
    "РАЗМЕР ОБЪЯВЛЕННЫХ ДИВИДЕНДОВ, РУБ.",
    "Дата, на которую определяются лица, имеющие право на получение дивидендов",
)


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
    content_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    status: int = 200,
) -> tuple[IssuerDividendsSource, MapTransport]:
    transport = MapTransport(FetchResponse(status, content_type, body))
    return IssuerDividendsSource(transport=transport, clock=lambda: CLOCK), transport


def _xlsx(rows: list[tuple[object, ...]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(list(row))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _declared_row(
    year: str,
    period: str,
    amount: object,
    total: object,
    record: object,
    payment: object | None = None,
) -> tuple[object, ...]:
    row: tuple[object, ...] = (year, period, amount, total, record)
    if payment is not None:
        return (*row, payment)
    return row


def test_saved_lukoil_archive_keeps_only_fields_present_in_the_sheet() -> None:
    body = (FIXTURES / "lukoil_declared.xlsx").read_bytes()
    source, transport = _source(body)
    artifacts = source.fetch_sample(limit=100)
    assert transport.calls == [SOURCE_URL]
    assert "cci" not in SOURCE_URL
    assert len(artifacts) == EVENT_CAP
    assert len(artifacts) == 30
    first = artifacts[0]
    assert first.event_date == date(2026, 5, 4)
    assert first.period_end == date(2025, 12, 31)
    assert first.period_end != first.event_date
    assert first.published_at is None
    assert first.published_at_precision == PublishedAtPrecision.UNKNOWN
    assert first.historical_pit_quality == PitQuality.RESEARCH_ONLY
    assert first.historical_pit_quality != PitQuality.PIT_VERIFIED
    assert first.first_observed_at == CLOCK
    assert first.quality_status == RecordQuality.ACCEPTED
    assert first.chronology_errors() == ()
    assert "payment_date_absent" in first.limitations
    assert "record_date_is_not_publication" in first.limitations
    assert "sample_capped_at_30" in first.limitations
    observation = source.parse(first, body)[0]
    assert observation.value == 278
    assert observation.value != 192616681836
    assert observation.currency == "RUB"
    assert observation.extra["record_date"] == "2026-05-04"
    assert observation.extra["payment_date"] is None
    assert observation.extra["payment_year_label"] == "2026*"
    assert observation.extra["period_end"] == "2025-12-31"
    assert observation.period_end == date(2025, 12, 31)
    second = artifacts[1]
    assert second.reporting_period == "M9:2025"
    assert second.period_end == date(2025, 9, 30)
    assert second.event_date == date(2026, 1, 12)
    approval = next(
        item for item in artifacts if "agm_date_in_period_text_not_used_as_published_at" in item.limitations
    )
    assert approval.published_at is None
    assert approval.event_date == date(2022, 12, 21)
    assert approval.period_end is None
    assert approval.historical_pit_quality == PitQuality.RESEARCH_ONLY
    parsed = source.parse(approval, body)[0]
    assert parsed.extra["shareholder_approval_date"] == "2022-12-05"
    assert parsed.extra["payment_date"] is None
    assert parsed.period_end is None
    assert all(item.historical_pit_quality == PitQuality.RESEARCH_ONLY for item in artifacts)
    assert all(source.parse(item, body)[0].extra["payment_date"] is None for item in artifacts)
    assert all(item.value != 0 for item in (source.parse(artifact, body)[0] for artifact in artifacts))
    coverage = source.inspect_coverage()
    assert coverage.status == AdapterStatus.PARTIAL
    assert "declared_rows_in_workbook:46" in coverage.limitations
    assert "events_emitted:30" in coverage.limitations
    assert "pit:RESEARCH_ONLY" in coverage.limitations
    assert "zero_invented_amounts" not in coverage.limitations
    note = json.loads((FIXTURES / "probe_note.json").read_text(encoding="utf-8"))
    assert note["url"] == SOURCE_URL
    assert note["http_status"] == 200
    assert note["parsed_events_in_workbook"] == 46
    assert note["events_emitted"] == 30
    assert note["fields_present"]["record_date"] is True
    assert note["fields_present"]["amount_per_share"] is True
    assert note["fields_present"]["payment_date"] is False
    assert note["fields_present"]["publication_timestamp"] is False
    assert note["pit"] == "RESEARCH_ONLY"
    assert note["status"] == "PARTIAL"


def test_explicit_payment_column_is_kept_off_period_end() -> None:
    header = (*HEADER, "Дата выплаты")
    body = _xlsx(
        [
            header,
            _declared_row("2026*", "2025 года", "278 ао", 192616681836, "4 мая 2026 г.", "18 августа 2026 г."),
            ("* - номинальным держателям в срок не позднее 18 мая 2026 г.", None, None, None, None, None),
            _declared_row("2026**", "девяти месяцев 2025 года", "100 ап", 1, "12 января 2026 г.", "1 февраля 2026 г."),
            _declared_row("2025**", "2024 года", "541 ао", 10, "3 июня 2025 г.", "20 июля 2025 г."),
        ]
    )
    source, _transport = _source(body)
    artifacts = source.fetch_sample()
    assert len(artifacts) == 2
    first = source.parse(artifacts[0], body)[0]
    assert first.extra["payment_date"] == "2026-08-18"
    assert first.extra["record_date"] == "2026-05-04"
    assert first.period_end == date(2025, 12, 31)
    assert first.period_end.isoformat() != first.extra["payment_date"]
    assert first.value == 278
    second = source.parse(artifacts[1], body)[0]
    assert second.extra["payment_date"] == "2025-07-20"
    assert second.extra["record_date"] == "2025-06-03"
    assert "100" not in {str(first.value), str(second.value)}


def test_blank_amount_is_not_filled_with_zero() -> None:
    body = _xlsx(
        [
            HEADER,
            _declared_row("2024*", "2023 года", None, 999, "1 июля 2024 г."),
            _declared_row("2024**", "2023 года", "0 ао", 999, "2 июля 2024 г."),
        ]
    )
    source, _transport = _source(body)
    assert source.fetch_sample()[0].fetch_status == FetchStatus.EMPTY
    assert source.parse(source.fetch_sample()[0], body) == ()
    coverage = source.inspect_coverage()
    assert coverage.status == AdapterStatus.PARTIAL
    assert "amount_absent" in coverage.limitations
    assert "zero_invented_amounts" in coverage.limitations


def test_antibot_html_and_pdf_emit_no_rubles() -> None:
    html = b"<html><body>Forbidden request-id captcha</body></html>"
    source, transport = _source(html, content_type="text/html", status=403)
    artifact = source.fetch_sample()[0]
    assert transport.calls == [SOURCE_URL]
    assert artifact.fetch_status == FetchStatus.FORBIDDEN
    assert artifact.event_date is None
    assert artifact.published_at is None
    assert artifact.historical_pit_quality == PitQuality.RESEARCH_ONLY
    assert source.parse(artifact, html) == ()
    assert source.inspect_coverage().status == AdapterStatus.BLOCKED

    pdf = b"%PDF-1.4 dividend 412.13"
    pdf_source, _transport = _source(pdf, content_type="application/pdf", status=200)
    pdf_artifact = pdf_source.fetch_sample()[0]
    assert pdf_artifact.fetch_status == FetchStatus.UNSUPPORTED
    assert "pdf_not_parsed" in pdf_artifact.limitations
    assert pdf_source.parse(pdf_artifact, pdf) == ()
    assert pdf_source.inspect_coverage().status == AdapterStatus.BLOCKED
    assert pdf_source.validate(()) == ()


def test_range_uses_record_date_and_validate_rejects_an_unevidenced_amount() -> None:
    body = (FIXTURES / "lukoil_declared.xlsx").read_bytes()
    source, _transport = _source(body)
    window = source.fetch_range(start=date(2022, 12, 21), end=date(2022, 12, 21), limit=30)
    assert window
    assert {item.event_date for item in window} == {date(2022, 12, 21)}
    approval = next(item for item in window if item.period_end is None)
    checked = source.validate(source.parse(approval, body))
    assert checked[0].quality_status == RecordQuality.ACCEPTED
    bare = ParsedObservation(
        metric_id="issuer.dividend.amount_per_share",
        source_id="IR-05",
        content_hash="abc",
        normalization_version="issuer_dividend_dps_v1",
        quality_status=RecordQuality.ACCEPTED,
        value=1,
        issuer_identity={"secid": "LKOH"},
    )
    quarantined = source.validate((bare,))[0]
    assert quarantined.quality_status == RecordQuality.QUARANTINE
    assert quarantined.value == 1


def test_adapter_does_not_reference_cci_stage_or_memory_writes() -> None:
    text = SOURCE_PATH.read_text(encoding="utf-8")
    assert "cci/corp-actions" not in text
    assert "stage_1000" not in text
    assert "prospective_captures" not in text
