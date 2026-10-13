"""CBR-05 access check. Fixtures only; this module does not call CBR."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    ParsedObservation,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.cbr_reviews.source import (
    MAX_ROWS,
    PROBED_HTTP_STATUS,
    PROBED_ON,
    SOURCE_ID,
    SOURCE_URL,
    CbrReviewsSource,
    HttpResult,
)

CLOCK = datetime(2026, 10, 13, 5, 30, tzinfo=UTC)
PACKAGE = Path(__file__).resolve().parents[3] / "app" / "modules" / "historical" / "sources" / "cbr_reviews"
PROBE_NOTE = PACKAGE / "probe_note.json"

HTML_REVIEW = """<!DOCTYPE html>
<html><head><title>Обзор банковского сектора</title></head>
<body>
<h1>Обзор банковского сектора Российской Федерации</h1>
<p><a href="/Collection/Collection/File/1/razv_bs.pdf">PDF</a></p>
<table><tr><td>Активы</td><td>999999</td></tr></table>
</body></html>
""".encode()

PDF_REVIEW = b"%PDF-1.4\n1 0 obj\nstream\nAssets 888888\nendstream\n"
XML_TABLE = """<?xml version="1.0" encoding="utf-8"?>
<table><tr><td>Активы</td><td>777777</td></tr></table>
""".encode()
BARE_JSON = b"[12345, 67890]"
CSV_TABLE = b"""period_end,value,published_at,metric_id
2024-01-31,10.5,2024-02-20T12:00:00+03:00,sector.assets
2024-02-29,0,2024-03-15,sector.assets
2024-03-31,,2024-04-10T08:00:00+03:00,sector.assets
"""
SEMICOLON_CSV = b"period_end;value;published_at\n31.01.2024;10,5;20.02.2024\n"
JSON_TABLE = """{"rows": [
  {"period_end": "2024-08-31", "value": "8,75", "published_at": "2024-09-10"},
  {"indicator": "Активы 555555", "period_end": "2024-09-30"}
]}""".encode()
XML_ROWS = b"""<?xml version="1.0" encoding="utf-8"?>
<Reviews>
  <Review>
    <period_end>2024-06-30</period_end>
    <value>4.25</value>
    <published_at>2024-07-15T11:30:00+03:00</published_at>
    <metric_id>sector.assets</metric_id>
  </Review>
</Reviews>
"""
DATE_COLUMN = b"date,value\n2024-05-01,3.5\n"
COLLISION = b"period_end,value,published_at\n2024-01-31,1.0,2024-01-31T15:00:00+03:00\n"
NAIVE = b"period_end,value,published_at\n2024-01-31,2.5,2024-02-20T12:00:00\n"


class _FakeTransport:
    def __init__(self, result: HttpResult) -> None:
        self.result = result
        self.urls: list[str] = []

    def request(self, url: str) -> HttpResult:
        self.urls.append(url)
        return self.result


def _source(result: HttpResult) -> tuple[CbrReviewsSource, _FakeTransport]:
    transport = _FakeTransport(result)
    return CbrReviewsSource(transport, now=CLOCK), transport


def _http(status: int, body: bytes, content_type: str | None) -> HttpResult:
    return HttpResult(url=SOURCE_URL, status=status, body=body, content_type=content_type)


def _visible(artifact: object, observations: tuple[ParsedObservation, ...]) -> str:
    item = artifact
    parts = [
        getattr(item, "title", "") or "",
        getattr(item, "external_document_id", ""),
        getattr(item, "document_type", ""),
        " ".join(getattr(item, "limitations", ())),
        " ".join(getattr(item, "entity_identifiers", {}).values()),
        getattr(item, "reporting_period", "") or "",
        str(getattr(item, "published_at", "")),
        " ".join(str(obs.value) for obs in observations),
        " ".join(obs.evidence or "" for obs in observations),
        " ".join(obs.metric_id for obs in observations),
        " ".join(" ".join(obs.extra.values()) for obs in observations),
    ]
    return " ".join(parts)


def test_recorded_probe_is_one_catalog_404() -> None:
    note = json.loads(PROBE_NOTE.read_text(encoding="utf-8"))
    assert note["url"] == SOURCE_URL
    assert note["http_status"] == PROBED_HTTP_STATUS == 404
    assert note["probed_on"] == PROBED_ON
    assert note["rows"] == 0
    assert note["pit"] == "RESEARCH_ONLY"
    assert note["follow_up_requests"] == 0
    assert note["body_retained"] is False
    assert note["soap_forms_called"] is False
    assert SOURCE_ID == "CBR-05"


def test_package_does_not_wrap_soap_forms() -> None:
    text = (PACKAGE / "source.py").read_text(encoding="utf-8")
    assert "cbr_banks" not in text
    assert "cbr_rates" not in text
    assert "CreditOrgInfo" not in text
    assert "Data101FullXML" not in text


def test_catalog_404_is_blocked_and_not_a_metric() -> None:
    body = b"<!DOCTYPE html><html><body><table><td>999999</td></table></body></html>"
    source, transport = _source(_http(404, body, "text/html; charset=utf-8"))
    report = source.discover()
    artifact = source.fetch_sample(limit=30)[0]
    observations = source.parse(artifact, source.last_raw)

    assert transport.urls == [SOURCE_URL]
    assert report.status is AdapterStatus.BLOCKED
    assert report.earliest is None
    assert report.latest is None
    assert source.last_http_status == 404
    assert artifact.fetch_status is FetchStatus.FAILED
    assert artifact.document_type == "cbr_review_access"
    assert artifact.published_at is None
    assert artifact.published_at_precision is PublishedAtPrecision.UNKNOWN
    assert artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert artifact.first_observed_at == CLOCK
    assert artifact.first_observed_at != artifact.published_at
    assert artifact.chronology_errors() == ()
    assert "http_status=404" in artifact.limitations
    assert "zero_metrics" in artifact.limitations
    assert "not_soap_forms_101_102_123_135" in artifact.limitations
    assert observations == ()
    assert "999999" not in _visible(artifact, observations)
    assert source.inspect_coverage().status is AdapterStatus.BLOCKED
    assert transport.urls == [SOURCE_URL]


def test_html_and_pdf_publish_zero_metrics() -> None:
    html_source, _transport = _source(_http(200, HTML_REVIEW, "text/html"))
    html_report = html_source.discover()
    html_artifact = html_source.fetch_sample()[0]
    html_observations = html_source.parse(html_artifact, html_source.last_raw)
    assert html_report.status is AdapterStatus.PARTIAL
    assert html_artifact.fetch_status is FetchStatus.UNSUPPORTED
    assert "html_without_machine_readable_table" in html_artifact.limitations
    assert html_observations == ()
    assert html_artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert "999999" not in _visible(html_artifact, html_observations)

    pdf_source, _pdf_transport = _source(_http(200, PDF_REVIEW, "application/pdf"))
    pdf_artifact = pdf_source.fetch_sample()[0]
    pdf_observations = pdf_source.parse(pdf_artifact, pdf_source.last_raw)
    assert pdf_source.discover().status is AdapterStatus.PARTIAL
    assert "pdf_not_a_table" in pdf_artifact.limitations
    assert pdf_observations == ()
    assert "888888" not in _visible(pdf_artifact, pdf_observations)


def test_xml_markup_table_is_not_a_metric_table() -> None:
    source, _transport = _source(_http(200, XML_TABLE, "application/xml"))
    artifact = source.fetch_sample()[0]
    observations = source.parse(artifact, source.last_raw)
    assert artifact.document_type == "cbr_review_access"
    assert observations == ()
    assert "777777" not in _visible(artifact, observations)


def test_bare_json_numbers_are_not_metrics() -> None:
    source, _transport = _source(_http(200, BARE_JSON, "application/json"))
    artifact = source.fetch_sample()[0]
    observations = source.parse(artifact, source.last_raw)
    assert source.discover().status is AdapterStatus.PARTIAL
    assert artifact.fetch_status is FetchStatus.UNSUPPORTED
    assert observations == ()
    assert "12345" not in _visible(artifact, observations)


def test_csv_rows_keep_publication_time_separate_from_the_fetch_clock() -> None:
    source, transport = _source(_http(200, CSV_TABLE, "text/csv; charset=utf-8"))
    artifacts = source.fetch_sample(limit=1000)
    assert transport.urls == [SOURCE_URL]
    assert len(artifacts) == 3
    assert source.discover().status is AdapterStatus.PARTIAL
    assert "row_cap_100" not in source.discover().limitations
    first, second, third = artifacts
    assert first.period_end == date(2024, 1, 31)
    assert first.published_at == datetime(2024, 2, 20, 9, 0, tzinfo=UTC)
    assert first.published_at_precision is PublishedAtPrecision.TIMESTAMP
    assert first.historical_pit_quality is PitQuality.PIT_VERIFIED
    assert first.historical_availability_evidence == "cbr_reviews_published_at"
    assert first.first_observed_at == CLOCK
    assert first.chronology_errors() == ()
    first_obs = source.parse(first, source.last_raw)[0]
    assert first_obs.value == 10.5
    assert first_obs.metric_id == "sector.assets"
    assert first_obs.evidence == "value=10.5"
    assert first_obs.quality_errors() == ()

    assert second.period_end == date(2024, 2, 29)
    assert second.published_at == datetime(2024, 3, 15, tzinfo=UTC)
    assert second.published_at_precision is PublishedAtPrecision.DATE_ONLY
    assert second.historical_pit_quality is PitQuality.PIT_PROXY
    second_obs = source.parse(second, source.last_raw)[0]
    assert second_obs.value == 0
    assert "explicit_zero" in second_obs.limitations
    assert second_obs.quality_errors() == ()

    assert third.published_at == datetime(2024, 4, 10, 5, 0, tzinfo=UTC)
    assert source.parse(third, source.last_raw) == ()
    assert third.quality_status is RecordQuality.UNRESOLVED
    assert "10.5" not in (third.title or "")
    ranged = source.fetch_range(start=date(2024, 2, 1), end=date(2024, 2, 29), limit=1000)
    assert [item.period_end for item in ranged] == [date(2024, 2, 29)]
    assert transport.urls == [SOURCE_URL]


def test_semicolon_csv_uses_period_and_date_only_publication() -> None:
    source, _transport = _source(_http(200, SEMICOLON_CSV, "text/csv"))
    artifact = source.fetch_sample()[0]
    observation = source.parse(artifact, source.last_raw)[0]
    assert artifact.period_end == date(2024, 1, 31)
    assert artifact.published_at == datetime(2024, 2, 20, tzinfo=UTC)
    assert artifact.historical_pit_quality is PitQuality.PIT_PROXY
    assert artifact.published_at_precision is PublishedAtPrecision.DATE_ONLY
    assert observation.value == 10.5
    assert artifact.chronology_errors() == ()


def test_json_and_xml_tables_stop_at_the_value_column() -> None:
    json_source, _json_transport = _source(_http(200, JSON_TABLE, "application/json"))
    first, second = json_source.fetch_sample(limit=1000)
    first_obs = json_source.parse(first, json_source.last_raw)[0]
    assert first_obs.value == 8.75
    assert first.historical_pit_quality is PitQuality.PIT_PROXY
    assert first.published_at == datetime(2024, 9, 10, tzinfo=UTC)
    assert json_source.parse(second, json_source.last_raw) == ()
    assert "555555" not in _visible(second, ())
    assert "metric_label_not_used_as_metric_id" in second.limitations

    xml_source, _xml_transport = _source(_http(200, XML_ROWS, "application/xml"))
    artifact = xml_source.fetch_sample()[0]
    observation = xml_source.parse(artifact, xml_source.last_raw)[0]
    assert observation.value == 4.25
    assert observation.metric_id == "sector.assets"
    assert artifact.published_at == datetime(2024, 7, 15, 8, 30, tzinfo=UTC)
    assert artifact.historical_pit_quality is PitQuality.PIT_VERIFIED
    assert artifact.period_end == date(2024, 6, 30)
    assert artifact.chronology_errors() == ()
    assert xml_source.discover().earliest == date(2024, 6, 30)
    assert xml_source.discover().latest == date(2024, 6, 30)


def test_date_column_is_the_period_and_not_the_publication_time() -> None:
    source, _transport = _source(_http(200, DATE_COLUMN, "text/csv"))
    artifact = source.fetch_sample()[0]
    observation = source.parse(artifact, source.last_raw)[0]
    assert artifact.period_end == date(2024, 5, 1)
    assert artifact.published_at is None
    assert artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert "date_column_is_period_not_publication" in artifact.limitations
    assert observation.value == 3.5
    assert artifact.first_observed_at == CLOCK


def test_same_day_timestamp_is_not_a_chronology_error() -> None:
    source, _transport = _source(_http(200, COLLISION, "text/csv"))
    artifact = source.fetch_sample()[0]
    assert artifact.published_at_precision is PublishedAtPrecision.TIMESTAMP
    assert artifact.period_end == artifact.published_at.date()
    assert artifact.chronology_errors() == ()


def test_naive_timestamp_is_proxy_not_verified() -> None:
    source, _transport = _source(_http(200, NAIVE, "text/csv"))
    artifact = source.fetch_sample()[0]
    assert artifact.published_at == datetime(2024, 2, 20, 12, 0, tzinfo=UTC)
    assert artifact.historical_pit_quality is PitQuality.PIT_PROXY
    assert artifact.published_at_precision is PublishedAtPrecision.TIMESTAMP
    assert "naive_timestamp_assumed_utc" in artifact.limitations
    assert artifact.chronology_errors() == ()


def test_row_cap_is_100_even_when_the_caller_asks_for_more() -> None:
    start = date(2020, 1, 1)
    lines = ["period_end,value,published_at"]
    for offset in range(MAX_ROWS + 1):
        period = start + timedelta(days=offset)
        published = period + timedelta(days=10)
        lines.append(f"{period.isoformat()},{offset + 1}.0,{published.isoformat()}T12:00:00+00:00")
    body = ("\n".join(lines) + "\n").encode()
    source, transport = _source(_http(200, body, "text/csv"))
    artifacts = source.fetch_sample(limit=1000)
    assert len(artifacts) == MAX_ROWS == 100
    assert transport.urls == [SOURCE_URL]
    assert "row_cap_100" in artifacts[0].limitations
    assert source.parse(artifacts[-1], source.last_raw)[0].value == 100.0
    assert all(source.parse(item, source.last_raw)[0].value != 101.0 for item in artifacts)
    assert source.fetch_range(start=date(2020, 1, 1), end=date(2020, 1, 1), limit=1000)[0].period_end == date(
        2020, 1, 1
    )


def test_swapped_body_does_not_yield_the_other_payloads_metrics() -> None:
    source, _transport = _source(_http(200, CSV_TABLE, "text/csv"))
    artifact = source.fetch_sample()[0]
    assert source.parse(artifact, HTML_REVIEW) == ()


def test_validate_quarantines_an_accepted_observation_without_evidence() -> None:
    source, _transport = _source(_http(404, b"missing", "text/plain"))
    broken = ParsedObservation(
        metric_id="value",
        source_id=SOURCE_ID,
        content_hash="abc",
        normalization_version="cbr_reviews_access_v1",
        quality_status=RecordQuality.ACCEPTED,
        value=1.0,
    )
    checked = source.validate((broken,))
    assert checked[0].quality_status is RecordQuality.QUARANTINE
    assert "accepted_fact_requires_evidence" in checked[0].limitations


def test_negative_limit_does_not_request_the_catalog() -> None:
    source, transport = _source(_http(404, b"missing", "text/plain"))
    with pytest.raises(ValueError):
        source.fetch_sample(limit=-1)
    assert transport.urls == []


def test_forbidden_response_is_blocked() -> None:
    source, _transport = _source(_http(403, b"<html>captcha 999999</html>", "text/html"))
    artifact = source.fetch_sample()[0]
    assert source.discover().status is AdapterStatus.BLOCKED
    assert artifact.fetch_status is FetchStatus.FORBIDDEN
    assert source.parse(artifact, source.last_raw) == ()
    assert "999999" not in _visible(artifact, ())
