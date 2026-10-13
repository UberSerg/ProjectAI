"""CBR-04 gold accounting prices. The fixture is the live probe; tests do not call CBR."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.cbr_macro.source import (
    SAMPLE_END,
    SAMPLE_START,
    SOURCE_URL,
    CbrMacroSource,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cbr_gold_dragmet_sample.xml"
# Probe clock: file written 2026-10-13 08:31:22 UTC+3. Not a DateMet value.
PROBE_AT = datetime(2026, 10, 13, 5, 31, 22, tzinfo=UTC)

# Gold CodMet=1 from the 2026-10-13 DragMetDynamicXML probe. Other metals omitted.
GOLD = (
    (date(2024, 1, 10), 5886.06),
    (date(2024, 1, 11), 5848.46),
    (date(2024, 1, 12), 5785.30),
    (date(2024, 1, 13), 5749.64),
    (date(2024, 1, 16), 5794.64),
    (date(2024, 1, 17), 5776.36),
    (date(2024, 1, 18), 5789.66),
    (date(2024, 1, 19), 5734.52),
    (date(2024, 1, 20), 5734.04),
    (date(2024, 1, 23), 5737.50),
    (date(2024, 1, 24), 5714.43),
    (date(2024, 1, 25), 5741.86),
    (date(2024, 1, 26), 5770.98),
    (date(2024, 1, 27), 5824.35),
    (date(2024, 1, 30), 5815.14),
    (date(2024, 1, 31), 5805.98),
)


class _PayloadFetcher:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[tuple[date, date]] = []

    def fetch_gold(self, start: date, end: date) -> bytes:
        self.calls.append((start, end))
        return self.payload


class _HttpErrorFetcher:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.calls = 0

    def fetch_gold(self, start: date, end: date) -> bytes:
        self.calls += 1
        request = httpx.Request("POST", SOURCE_URL)
        response = httpx.Response(self.status_code, request=request)
        raise httpx.HTTPStatusError("cbr", request=request, response=response)


def _load() -> bytes:
    return FIXTURE.read_bytes()


def _source(payload: bytes) -> tuple[CbrMacroSource, _PayloadFetcher]:
    fetcher = _PayloadFetcher(payload)
    return CbrMacroSource(fetcher=fetcher, now=PROBE_AT), fetcher


def test_fetch_sample_uses_the_probed_window_and_keeps_gold_only() -> None:
    raw = _load()
    source, fetcher = _source(raw)
    artifacts = source.fetch_sample(limit=100)
    assert fetcher.calls == [(SAMPLE_START, SAMPLE_END)]
    assert len(artifacts) == 16
    assert len(GOLD) == 16
    assert [item.period_end for item in artifacts] == [item[0] for item in GOLD]
    assert source.inspect_coverage().status == AdapterStatus.READY
    assert source.inspect_coverage().earliest == date(2024, 1, 10)
    assert source.inspect_coverage().latest == date(2024, 1, 31)
    observations = [source.parse(artifact, raw)[0] for artifact in artifacts]
    assert [item.value for item in observations] == pytest.approx([item[1] for item in GOLD])
    assert all(item.extra["metal_code"] == "1" for item in observations)
    assert 66.4 not in [item.value for item in observations]


def test_accounting_date_is_not_a_publication_timestamp() -> None:
    raw = _load()
    source, _fetcher = _source(raw)
    artifacts = source.fetch_range(start=SAMPLE_START, end=SAMPLE_END, limit=100)
    for artifact in artifacts:
        assert artifact.first_observed_at == PROBE_AT
        assert artifact.period_end != artifact.first_observed_at.date()
        assert artifact.published_at is None
        assert artifact.published_at_precision == PublishedAtPrecision.UNKNOWN
        assert artifact.historical_availability_evidence is None
        assert artifact.historical_pit_quality == PitQuality.RESEARCH_ONLY
        assert artifact.historical_pit_quality != PitQuality.PIT_VERIFIED
        assert "cbr_datemet_is_accounting_date_not_publication_timestamp" in artifact.limitations
        assert artifact.chronology_errors() == ()
        assert artifact.source_url == SOURCE_URL
    observation = source.parse(artifacts[0], raw)[0]
    assert observation.quality_status == RecordQuality.ACCEPTED
    assert observation.evidence == "DragMetDynamicXML/DrgMet/CBR-04:2024-01-10"
    assert observation.unit == "rub_per_gram"
    assert observation.currency == "RUB"
    assert observation.period_end == date(2024, 1, 10)
    checked = source.validate((observation,))
    assert checked[0].quality_status == RecordQuality.ACCEPTED
    assert checked[0].quality_errors() == ()


def test_missing_and_zero_prices_are_not_accepted() -> None:
    raw = b"""<DragMetall>
      <DrgMet><DateMet>2024-01-10T00:00:00+03:00</DateMet><CodMet>1</CodMet><price></price></DrgMet>
      <DrgMet><DateMet>2024-01-11T00:00:00+03:00</DateMet><CodMet>1</CodMet><price>0</price></DrgMet>
      <DrgMet><DateMet>2024-01-12T00:00:00+03:00</DateMet><CodMet>1</CodMet></DrgMet>
    </DragMetall>"""
    source, _fetcher = _source(raw)
    artifacts = source.fetch_range(start=date(2024, 1, 1), end=date(2024, 1, 31), limit=100)
    observations = [source.parse(artifact, raw)[0] for artifact in artifacts]
    assert observations[0].value is None
    assert "gold_price_missing" in observations[0].limitations
    assert observations[1].value == 0.0
    assert observations[1].quality_status == RecordQuality.QUARANTINE
    assert "source_literal_zero" in observations[1].limitations
    assert observations[2].value is None
    assert source.inspect_coverage().status == AdapterStatus.PARTIAL


def test_duplicate_gold_date_is_quarantined() -> None:
    raw = b"""<DragMetall>
      <DrgMet><DateMet>2024-01-10T00:00:00+03:00</DateMet><CodMet>1</CodMet><price>5886.0600</price></DrgMet>
      <DrgMet><DateMet>2024-01-10T00:00:00+03:00</DateMet><CodMet>1</CodMet><price>1.00</price></DrgMet>
    </DragMetall>"""
    source, _fetcher = _source(raw)
    artifacts = source.fetch_range(start=date(2024, 1, 1), end=date(2024, 1, 31), limit=100)
    assert artifacts[0].quality_status == RecordQuality.ACCEPTED
    assert artifacts[1].quality_status == RecordQuality.QUARANTINE
    assert artifacts[1].external_document_id.endswith("#duplicate")
    assert source.parse(artifacts[1], raw)[0].value == pytest.approx(1.0)


def test_other_metals_do_not_become_gold_rows() -> None:
    raw = b"""<DragMetall>
      <DrgMet><DateMet>2024-01-10T00:00:00+03:00</DateMet><CodMet>2</CodMet><price>66.4000</price></DrgMet>
      <DrgMet><DateMet>2024-01-10T00:00:00+03:00</DateMet><CodMet>3</CodMet><price>2755.4100</price></DrgMet>
    </DragMetall>"""
    source, _fetcher = _source(raw)
    artifacts = source.fetch_range(start=SAMPLE_START, end=SAMPLE_END, limit=100)
    assert artifacts[0].fetch_status == FetchStatus.EMPTY
    assert source.inspect_coverage().status == AdapterStatus.PARTIAL
    assert "no_rows" in artifacts[0].limitations
    assert source.parse(artifacts[0], raw) == ()
    assert source.inspect_coverage().earliest is None


def test_sample_limit_never_exceeds_one_hundred_rows() -> None:
    parts: list[str] = []
    cursor = date(2020, 1, 1)
    for _ in range(101):
        parts.append(
            f"<DrgMet><DateMet>{cursor.isoformat()}T00:00:00+03:00</DateMet>"
            f"<CodMet>1</CodMet><price>5000.00</price></DrgMet>"
        )
        cursor = date.fromordinal(cursor.toordinal() + 1)
    raw = ("<DragMetall>" + "".join(parts) + "</DragMetall>").encode()
    source, _fetcher = _source(raw)
    with pytest.raises(ValueError, match="100"):
        source.fetch_range(start=date(2020, 1, 1), end=date(2020, 6, 1), limit=101)
    artifacts = source.fetch_range(start=date(2020, 1, 1), end=date(2020, 6, 1), limit=100)
    assert len(artifacts) == 100


def test_forbidden_and_rate_limit_stop_without_a_second_call() -> None:
    for code, fetch_status in ((403, FetchStatus.FORBIDDEN), (429, FetchStatus.RATE_LIMITED)):
        fetcher = _HttpErrorFetcher(code)
        source = CbrMacroSource(fetcher=fetcher, now=PROBE_AT)
        artifacts = source.fetch_sample(limit=30)
        assert fetcher.calls == 1
        assert artifacts[0].fetch_status == fetch_status
        assert source.inspect_coverage().status == AdapterStatus.BLOCKED
        assert f"http_{code}" in artifacts[0].limitations
        assert source.parse(artifacts[0], b"<DragMetall/>") == ()
        assert artifacts[0].historical_pit_quality == PitQuality.RESEARCH_ONLY


def test_html_payload_is_partial_and_has_no_invented_price() -> None:
    raw = b"<!DOCTYPE html><html><body><table><tr><td>5886</td></tr></table></body></html>"
    source, _fetcher = _source(raw)
    artifacts = source.fetch_range(start=SAMPLE_START, end=SAMPLE_END, limit=30)
    assert artifacts[0].fetch_status == FetchStatus.UNSUPPORTED
    assert source.inspect_coverage().status == AdapterStatus.PARTIAL
    assert "html_payload" in artifacts[0].limitations
    assert source.parse(artifacts[0], raw) == ()


def test_soap_fault_does_not_invent_a_price() -> None:
    raw = b"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Body><soap:Fault><faultstring>denied</faultstring></soap:Fault></soap:Body>
    </soap:Envelope>"""
    source, _fetcher = _source(raw)
    artifacts = source.fetch_range(start=SAMPLE_START, end=SAMPLE_END, limit=30)
    assert artifacts[0].fetch_status == FetchStatus.FAILED
    assert source.inspect_coverage().status == AdapterStatus.FAILED
    assert "soap_fault" in artifacts[0].limitations
    assert source.parse(artifacts[0], raw) == ()


def test_validate_quarantines_an_accepted_zero_without_an_explicit_mark() -> None:
    raw = _load()
    source, _fetcher = _source(raw)
    artifact = source.fetch_sample(limit=30)[0]
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
    raw = _load()
    source, _fetcher = _source(raw)
    artifact = source.fetch_sample(limit=30)[0]
    parsed = source.parse(artifact, b"<DragMetall></DragMetall>")
    assert parsed[0].value is None
    assert parsed[0].quality_status == RecordQuality.QUARANTINE
    assert "content_hash_mismatch" in parsed[0].limitations


def test_naive_clock_is_rejected() -> None:
    source = CbrMacroSource(fetcher=_PayloadFetcher(_load()), clock=lambda: datetime(2026, 10, 13, 8, 31, 22))
    with pytest.raises(ValueError, match="timezone-aware"):
        source.fetch_sample(limit=16)


def test_adapter_does_not_name_forbidden_write_targets() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "modules"
        / "historical"
        / "sources"
        / "cbr_macro"
        / "source.py"
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
