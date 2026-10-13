"""CBR rate adapters. Fixtures are short public excerpts; tests do not call CBR."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.domain.ports.market_data import ProviderFetchResult
from app.infrastructure.market.cbr import parse_cbr_fx, parse_cbr_soap
from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.cbr_rates.adapter import (
    SAMPLE_END,
    SAMPLE_START,
    SPECS,
    CbrSeriesSource,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FETCHED_AT = datetime(2026, 10, 12, 20, 15, tzinfo=UTC)
WINDOW = (date(2023, 12, 1), date(2024, 2, 15))


class _PayloadProvider:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[tuple[str, date, date]] = []

    def fetch_series(self, external_id: str, start_date: date, end_date: date) -> ProviderFetchResult:
        self.calls.append((external_id, start_date, end_date))
        return ProviderFetchResult(
            source="CBR",
            records=(),
            raw_payloads=(self.payload,),
            metadata={"external_id": external_id},
        )


class _HttpErrorProvider:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.calls = 0

    def fetch_series(self, external_id: str, start_date: date, end_date: date) -> ProviderFetchResult:
        self.calls += 1
        request = httpx.Request("POST", SPECS["CBR-01"].source_url)
        response = httpx.Response(self.status_code, request=request)
        raise httpx.HTTPStatusError("cbr", request=request, response=response)


def _source(source_id: str, payload: bytes) -> tuple[CbrSeriesSource, _PayloadProvider]:
    provider = _PayloadProvider(payload)
    source = CbrSeriesSource(SPECS[source_id], provider=provider, now=FETCHED_AT)
    return source, provider


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_fetch_sample_uses_cross_year_window_and_existing_client_contract() -> None:
    source, provider = _source("CBR-01", _load("cbr_key_rate_sample.xml"))
    artifacts = source.fetch_sample(limit=60)
    assert provider.calls == [("KEY_RATE", SAMPLE_START, SAMPLE_END)]
    assert SAMPLE_START.year != SAMPLE_END.year
    assert len(artifacts) == 4
    assert source.inspect_coverage().status == AdapterStatus.READY


def test_key_rate_rows_are_research_only_and_fetch_time_is_not_the_period() -> None:
    raw = _load("cbr_key_rate_sample.xml")
    source, _provider = _source("CBR-01", raw)
    artifacts = source.fetch_range(start=WINDOW[0], end=WINDOW[1], limit=60)
    assert [item.period_end for item in artifacts] == [
        date(2023, 12, 1),
        date(2023, 12, 15),
        date(2023, 12, 18),
        date(2024, 2, 15),
    ]
    observations = []
    for artifact in artifacts:
        assert artifact.first_observed_at == FETCHED_AT
        assert artifact.period_end != artifact.first_observed_at.date()
        assert artifact.published_at is None
        assert artifact.published_at_precision == PublishedAtPrecision.UNKNOWN
        assert artifact.historical_pit_quality == PitQuality.RESEARCH_ONLY
        assert artifact.chronology_errors() == ()
        parsed = source.parse(artifact, raw)
        assert len(parsed) == 1
        observations.append(parsed[0])
    assert [item.value for item in observations] == [15.0, 15.0, 16.0, 16.0]
    assert all(item.quality_status == RecordQuality.ACCEPTED for item in observations)
    assert all(item.evidence for item in observations)


def test_usd_rub_matches_existing_fx_parser_and_has_no_publication_timestamp() -> None:
    raw = _load("cbr_usd_rub_sample.xml")
    source, provider = _source("CBR-02", raw)
    artifacts = source.fetch_range(start=WINDOW[0], end=WINDOW[1], limit=60)
    assert provider.calls[0][0] == "USD_RUB_CBR"
    points = parse_cbr_fx(raw)
    observations = [source.parse(artifact, raw)[0] for artifact in artifacts]
    assert [item.value for item in observations] == pytest.approx([float(point.value) for point in points])
    assert observations[1].extra["raw_value"] == "90,4040"
    assert artifacts[0].historical_pit_quality == PitQuality.RESEARCH_ONLY
    assert artifacts[0].first_observed_at == FETCHED_AT
    assert source.inspect_coverage().earliest == date(2023, 12, 1)
    assert source.inspect_coverage().latest == date(2024, 2, 15)


def test_ruonia_uses_dateupdate_timestamp_and_not_the_overnight_date() -> None:
    raw = _load("cbr_ruonia_sample.xml")
    assert parse_cbr_soap(raw) == []
    source, _provider = _source("CBR-03", raw)
    artifacts = source.fetch_range(start=WINDOW[0], end=WINDOW[1], limit=60)
    assert len(artifacts) == 2
    first, second = artifacts
    assert first.period_end == date(2023, 12, 1)
    assert first.published_at == datetime.fromisoformat("2023-12-04T14:10:49.320000+03:00")
    assert first.published_at_precision == PublishedAtPrecision.TIMESTAMP
    assert first.historical_pit_quality == PitQuality.PIT_PROXY
    assert first.historical_availability_evidence == "cbr_ruonia_DateUpdate"
    assert "DateUpdate_is_feed_update_time" in first.limitations
    assert first.first_observed_at == FETCHED_AT
    assert first.first_observed_at != first.published_at
    assert first.chronology_errors() == ()
    observation = source.parse(first, raw)[0]
    assert observation.value == pytest.approx(14.9)
    assert observation.extra["volume_billion_rub"] == "1005.5600"
    assert second.published_at == datetime.fromisoformat("2024-02-16T14:06:53.037000+03:00")
    assert second.historical_pit_quality == PitQuality.PIT_PROXY
    assert "DateUpdate_is_feed_update_time" in second.limitations
    assert source.inspect_coverage().status == AdapterStatus.READY


def test_missing_rate_is_not_stored_as_zero() -> None:
    raw = b"""<?xml version="1.0" encoding="utf-8"?>
    <KeyRate xmlns="">
      <KR><DT>2024-01-10T00:00:00+03:00</DT><Rate></Rate></KR>
      <KR><DT>2024-01-11T00:00:00+03:00</DT><Rate>0</Rate></KR>
      <KR><DT>2024-01-12T00:00:00+03:00</DT></KR>
    </KeyRate>
    """
    source, _provider = _source("CBR-01", raw)
    artifacts = source.fetch_range(start=date(2024, 1, 1), end=date(2024, 1, 31), limit=60)
    observations = [source.parse(artifact, raw)[0] for artifact in artifacts]
    assert observations[0].value is None
    assert observations[0].quality_status == RecordQuality.QUARANTINE
    assert "key_rate_missing" in observations[0].limitations
    assert observations[1].value == 0.0
    assert observations[1].quality_status == RecordQuality.QUARANTINE
    assert "source_literal_zero" in observations[1].limitations
    assert observations[2].value is None
    assert source.inspect_coverage().status == AdapterStatus.PARTIAL


def test_fx_missing_value_and_nominal_are_quarantined() -> None:
    raw = """<?xml version="1.0" encoding="windows-1251"?>
    <ValCurs>
      <Record Date="11.01.2024" Id="R01235"><Nominal>1</Nominal><Value></Value></Record>
      <Record Date="12.01.2024" Id="R01235"><Value>90,00</Value></Record>
    </ValCurs>
    """.encode("windows-1251")
    source, _provider = _source("CBR-02", raw)
    artifacts = source.fetch_range(start=date(2024, 1, 1), end=date(2024, 1, 31), limit=60)
    observations = [source.parse(artifact, raw)[0] for artifact in artifacts]
    assert observations[0].value is None
    assert "fx_value_missing" in observations[0].limitations
    assert observations[1].value is None
    assert "fx_nominal_missing" in observations[1].limitations


def test_duplicate_period_is_quarantined() -> None:
    raw = b"""<KeyRate>
      <KR><DT>2024-01-10T00:00:00+03:00</DT><Rate>16.00</Rate></KR>
      <KR><DT>2024-01-10T00:00:00+03:00</DT><Rate>16.50</Rate></KR>
    </KeyRate>"""
    source, _provider = _source("CBR-01", raw)
    artifacts = source.fetch_range(start=date(2024, 1, 1), end=date(2024, 1, 31), limit=60)
    assert artifacts[0].quality_status == RecordQuality.ACCEPTED
    assert artifacts[1].quality_status == RecordQuality.QUARANTINE
    assert artifacts[1].external_document_id.endswith("#duplicate")
    assert source.parse(artifacts[1], raw)[0].value == pytest.approx(16.5)


def test_same_day_ruonia_timestamp_stays_a_proxy() -> None:
    raw = b"""<Ruonia><ro>
      <D0>2024-01-10T00:00:00+03:00</D0>
      <ruo>15.00</ruo>
      <DateUpdate>2024-01-10T14:00:00+03:00</DateUpdate>
    </ro></Ruonia>"""
    source, _provider = _source("CBR-03", raw)
    artifact = source.fetch_range(start=date(2024, 1, 1), end=date(2024, 1, 31), limit=60)[0]
    assert artifact.historical_pit_quality == PitQuality.PIT_PROXY
    assert artifact.published_at_precision == PublishedAtPrecision.DATE_ONLY
    assert "DateUpdate_is_feed_update_time" in artifact.limitations
    assert artifact.chronology_errors() == ()


def test_sample_limit_never_exceeds_sixty_rows() -> None:
    parts: list[str] = []
    cursor = date(2020, 1, 1)
    for _ in range(70):
        parts.append(f"<KR><DT>{cursor.isoformat()}T00:00:00+03:00</DT><Rate>7.50</Rate></KR>")
        cursor += timedelta(days=3)
    raw = ("<KeyRate>" + "".join(parts) + "</KeyRate>").encode()
    source, _provider = _source("CBR-01", raw)
    with pytest.raises(ValueError):
        source.fetch_range(start=date(2020, 1, 1), end=date(2021, 1, 1), limit=61)
    artifacts = source.fetch_range(start=date(2020, 1, 1), end=date(2021, 1, 1), limit=60)
    assert len(artifacts) == 60
    assert artifacts[0].period_end == date(2020, 1, 1)


def test_forbidden_and_rate_limit_stop_without_a_second_call() -> None:
    for code, fetch_status in ((403, FetchStatus.FORBIDDEN), (429, FetchStatus.RATE_LIMITED)):
        provider = _HttpErrorProvider(code)
        source = CbrSeriesSource(SPECS["CBR-01"], provider=provider, now=FETCHED_AT)
        artifacts = source.fetch_sample(limit=30)
        assert provider.calls == 1
        assert artifacts[0].fetch_status == fetch_status
        assert source.inspect_coverage().status == AdapterStatus.BLOCKED
        assert source.parse(artifacts[0], b"<KeyRate/>") == ()


def test_html_payload_is_partial_and_not_parsed_as_rates() -> None:
    raw = b"<!DOCTYPE html><html><body><table><tr><td>16</td></tr></table></body></html>"
    source, _provider = _source("CBR-01", raw)
    artifacts = source.fetch_range(start=WINDOW[0], end=WINDOW[1], limit=30)
    assert artifacts[0].fetch_status == FetchStatus.UNSUPPORTED
    assert source.inspect_coverage().status == AdapterStatus.PARTIAL
    assert source.parse(artifacts[0], raw) == ()


def test_validate_quarantines_an_accepted_zero_without_an_explicit_mark() -> None:
    raw = _load("cbr_key_rate_sample.xml")
    source, _provider = _source("CBR-01", raw)
    artifact = source.fetch_range(start=WINDOW[0], end=WINDOW[1], limit=60)[0]
    observation = source.parse(artifact, raw)[0]
    forged = observation.__class__(
        metric_id=observation.metric_id,
        source_id=observation.source_id,
        content_hash=observation.content_hash,
        normalization_version=observation.normalization_version,
        quality_status=RecordQuality.ACCEPTED,
        value=0,
        evidence="row",
    )
    checked = source.validate((forged,))
    assert checked[0].quality_status == RecordQuality.QUARANTINE
    assert "zero_requires_explicit_zero_mark" in checked[0].limitations


def test_content_hash_mismatch_does_not_invent_a_value() -> None:
    raw = _load("cbr_usd_rub_sample.xml")
    source, _provider = _source("CBR-02", raw)
    artifact = source.fetch_range(start=WINDOW[0], end=WINDOW[1], limit=60)[0]
    parsed = source.parse(artifact, b"<ValCurs></ValCurs>")
    assert parsed[0].value is None
    assert parsed[0].quality_status == RecordQuality.QUARANTINE


def test_adapter_does_not_name_forbidden_write_targets() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "modules"
        / "historical"
        / "sources"
        / "cbr_rates"
        / "adapter.py"
    )
    body = source.read_text(encoding="utf-8")
    for name in (
        "prospective_captures",
        "signal_outputs",
        "committee_decisions",
        "shadow.orders",
        "broker.executions",
        "polza",
    ):
        assert name not in body
