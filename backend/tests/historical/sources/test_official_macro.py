"""Offline tests for INT-03 and INT-04. No live HTTP."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from urllib.error import URLError

import pytest

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.macro.transport import HttpResult
from app.modules.historical.sources.official_macro import (
    CONTEXT_STREAM_ID,
    DISCOVERY_NOTES,
    MAX_OBSERVATIONS,
    SOURCE_ID,
    SOURCE_URL,
    OfficialMacroSource,
)

FIXTURE = Path(__file__).parent / "fixtures" / "cbr_xml_metall_2026-09.xml"
FETCHED_AT = datetime(2026, 10, 13, 5, 30, tzinfo=UTC)


class _FakeTransport:
    def __init__(self, result: HttpResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        del data, headers
        self.calls.append(url)
        return self.result


class _RaisingTransport:
    def request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        del url, data, headers
        raise URLError("certificate verify failed")


def _clock() -> datetime:
    return FETCHED_AT


def _source(status: int, body: bytes) -> tuple[_FakeTransport, OfficialMacroSource]:
    transport = _FakeTransport(HttpResult(url=SOURCE_URL, status=status, body=body))
    return transport, OfficialMacroSource(transport, now=_clock)


def _live_body() -> bytes:
    return FIXTURE.read_bytes()


def test_verified_window_parses_without_inventing_a_unit_or_timestamp() -> None:
    transport, source = _source(200, _live_body())
    report = source.discover()
    access = source.access_check()
    context = source.context_map()
    artifact = source.fetch_sample(limit=MAX_OBSERVATIONS)[0]
    observations = source.validate(source.parse(artifact, source.last_raw))

    assert report.status is AdapterStatus.READY
    assert report.earliest == date(2026, 9, 1)
    assert report.latest == date(2026, 9, 30)
    assert report.formats == ("xml",)
    assert access.stream_id == SOURCE_ID
    assert access.http_status == 200
    assert access.blocked is False
    assert access.challenge is False
    assert access.api_key_sent is False
    assert access.row_count == 88
    assert context.stream_id == CONTEXT_STREAM_ID
    assert context.status is AdapterStatus.READY
    assert context.pit_quality is PitQuality.RESEARCH_ONLY
    assert context.publication_timestamp_present is False
    assert context.row_count == 88
    assert context.earliest == date(2026, 9, 1)
    assert context.latest == date(2026, 9, 30)
    assert [item.metal_code for item in context.series] == ["1", "2", "3", "4"]
    assert [item.documented_name for item in context.series] == [
        "gold",
        "silver",
        "platinum",
        "palladium",
    ]
    assert all(item.name_in_payload is False for item in context.series)
    assert all(item.unit_in_payload is False for item in context.series)
    assert all(item.observation_count == 22 for item in context.series)
    assert len(observations) == 88
    assert observations[0].period_end == date(2026, 9, 1)
    assert observations[0].extra["metal_code"] == "1"
    assert observations[0].value == pytest.approx(12671.47)
    assert observations[0].extra["sell"] == pytest.approx(12671.47)
    assert observations[0].unit is None
    assert observations[0].currency is None
    assert observations[-1].period_end == date(2026, 9, 30)
    assert observations[-1].extra["metal_code"] == "4"
    assert observations[-1].value == pytest.approx(3309.57)
    assert artifact.published_at is None
    assert artifact.published_at_precision is PublishedAtPrecision.UNKNOWN
    assert artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert artifact.historical_availability_evidence is None
    assert artifact.fetch_status is FetchStatus.OK
    assert artifact.first_observed_at == FETCHED_AT
    assert artifact.chronology_errors() == ()
    assert "no_publication_timestamp" in artifact.limitations
    assert "api_key_not_sent" in artifact.limitations
    assert all(item.quality_errors() == () for item in observations)
    assert all(item.quality_status is RecordQuality.ACCEPTED for item in observations)
    assert transport.calls
    assert all("api_key" not in url for url in transport.calls)
    assert all("eia.gov" not in url for url in transport.calls)
    assert "eia_not_requested" in DISCOVERY_NOTES


def test_sample_limit_keeps_the_latest_quotations() -> None:
    _transport, source = _source(200, _live_body())
    artifact = source.fetch_sample(limit=4)[0]
    observations = source.parse(artifact, source.last_raw)

    assert len(observations) == 4
    assert [item.period_end for item in observations] == [date(2026, 9, 30)] * 4
    assert [item.extra["metal_code"] for item in observations] == ["1", "2", "3", "4"]
    assert observations[0].value == pytest.approx(11250.09)
    assert observations[1].value == pytest.approx(166.48)
    assert observations[2].value == pytest.approx(4700.99)
    assert observations[3].value == pytest.approx(3309.57)


def test_range_keeps_one_day() -> None:
    _transport, source = _source(200, _live_body())
    artifact = source.fetch_range(start=date(2026, 9, 1), end=date(2026, 9, 1), limit=100)[0]
    observations = source.parse(artifact, source.last_raw)

    assert len(observations) == 4
    assert observations[0].extra["metal_code"] == "1"
    assert observations[0].value == pytest.approx(12671.47)
    assert all(item.period_end == date(2026, 9, 1) for item in observations)


def test_cap_drops_the_oldest_synthetic_point() -> None:
    rows = []
    for offset in range(MAX_OBSERVATIONS + 1):
        quotation = date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + offset)
        rows.append(
            f'<Record Date="{quotation.day:02d}.{quotation.month:02d}.{quotation.year}" '
            f'Code="1"><Buy>{offset + 1},00</Buy><Sell>{offset + 1},00</Sell></Record>'
        )
    body = ('<?xml version="1.0" encoding="windows-1251"?><Metall>' + "".join(rows) + "</Metall>").encode("ascii")
    _transport, source = _source(200, body)
    artifact = source.fetch_sample(limit=MAX_OBSERVATIONS + 50)[0]
    observations = source.parse(artifact, source.last_raw)

    assert len(observations) == MAX_OBSERVATIONS
    assert observations[0].value == pytest.approx(2.0)
    assert observations[-1].value == pytest.approx(101.0)
    assert "api_key" not in artifact.source_url


def test_explicit_zero_is_marked() -> None:
    body = (
        b'<?xml version="1.0" encoding="windows-1251"?>'
        b'<Metall><Record Date="01.09.2026" Code="2">'
        b"<Buy>0,00</Buy><Sell>0,00</Sell></Record></Metall>"
    )
    _transport, source = _source(200, body)
    artifact = source.fetch_sample(limit=5)[0]
    observations = source.validate(source.parse(artifact, source.last_raw))

    assert len(observations) == 1
    assert observations[0].value == 0
    assert "explicit_zero" in observations[0].limitations
    assert observations[0].quality_errors() == ()


def test_buy_is_kept_when_sell_differs() -> None:
    body = (
        b'<?xml version="1.0" encoding="windows-1251"?>'
        b'<Metall><Record Date="02.09.2026" Code="1">'
        b"<Buy>10,00</Buy><Sell>12,00</Sell></Record></Metall>"
    )
    _transport, source = _source(200, body)
    observations = source.parse(source.fetch_sample(limit=5)[0], source.last_raw)

    assert len(observations) == 1
    assert observations[0].value == pytest.approx(10.0)
    assert observations[0].extra["sell"] == pytest.approx(12.0)
    assert "buy_sell_differ" in observations[0].limitations


def test_missing_buy_is_not_filled() -> None:
    body = (
        b'<?xml version="1.0" encoding="windows-1251"?>'
        b"<Metall>"
        b'<Record Date="01.09.2026" Code="1"><Sell>10,00</Sell></Record>'
        b'<Record Date="01.09.2026" Code="2"><Buy>5,50</Buy><Sell>5,50</Sell></Record>'
        b"</Metall>"
    )
    _transport, source = _source(200, body)
    observations = source.parse(source.fetch_sample(limit=10)[0], source.last_raw)

    assert len(observations) == 1
    assert observations[0].extra["metal_code"] == "2"
    assert observations[0].value == pytest.approx(5.5)


def test_forbidden_body_yields_zero_prices() -> None:
    body = (
        b'<?xml version="1.0" encoding="windows-1251"?>'
        b'<Metall><Record Date="01.09.2026" Code="1">'
        b"<Buy>99999,99</Buy><Sell>99999,99</Sell></Record></Metall>"
    )
    _transport, source = _source(403, body)
    report = source.discover()
    access = source.access_check()
    context = source.context_map()
    observations = source.parse(source.fetch_sample()[0], source.last_raw)

    assert report.status is AdapterStatus.BLOCKED
    assert report.earliest is None
    assert access.blocked is True
    assert access.http_status == 403
    assert access.row_count == 0
    assert context.row_count == 0
    assert context.series == ()
    assert context.pit_quality is PitQuality.RESEARCH_ONLY
    assert observations == ()
    assert "http_status=403" in context.limitations


def test_challenge_page_yields_zero_prices() -> None:
    body = b"<html><title>Just a moment</title><body>99999.99</body></html>"
    _transport, source = _source(200, body)
    report = source.discover()
    access = source.access_check()
    observations = source.parse(source.fetch_sample()[0], source.last_raw)

    assert report.status is AdapterStatus.BLOCKED
    assert access.challenge is True
    assert access.blocked is True
    assert access.row_count == 0
    assert observations == ()


def test_tls_failure_does_not_invent_prices() -> None:
    source = OfficialMacroSource(_RaisingTransport(), now=_clock)
    report = source.discover()
    observations = source.parse(source.fetch_sample()[0], source.last_raw)

    assert report.status is AdapterStatus.FAILED
    assert source.last_http_status == 0
    assert observations == ()
