"""Offline tests for ROS-02, ROS-03, and ROS-04. No live HTTP."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.macro import (
    RosstatIndustrialProductionSource,
    RosstatUnemploymentSource,
)
from app.modules.historical.sources.macro.rosstat_industry import (
    INDUSTRY_GRID_URL,
    INDUSTRY_PAGE_URL,
    UNEMPLOYMENT_GRID_URL,
    UNEMPLOYMENT_PAGE_URL,
)
from app.modules.historical.sources.macro.rosstat_meta import assess_publication
from app.modules.historical.sources.macro.transport import HttpResult

FETCHED_AT = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)
INDUSTRY_LABELS = {
    'dim57940': (
        'Собирательная классификационная группировка видов экономической деятельности '
        '&quot;Промышленность&quot; на основе ОКВЭД2 (КДЕС Ред. 2)'
    ),
    'dim57937': 'Отчетный месяц к соответствующему месяцу предыдущего года',
    'dim57831': 'Российская Федерация',
}
INDUSTRY_CELLS = (
    ('dim2017_1540283_d111354279_i4596', '106,6'),
    ('dim2017_1540282_d111354279_i4625', '101,6'),
    ('dim2017_1540236_d111354279_i4630', '103,6'),
    ('dim2017_1540229_d111354279_i4627', '104,3'),
    ('dim2017_1540235_d111354279_i4629', '106,3'),
    ('dim2017_1540234_d111354279_i4628', '105,5'),
    ('dim2017_1540233_d111354279_i4632', '104,6'),
    ('dim2017_1540228_d111354279_i4631', '105,1'),
    ('dim2017_1540276_d111354279_i4635', '104'),
    ('dim2017_1540273_d111354279_i4634', '102,3'),
    ('dim2017_1540272_d111354279_i4633', '101,1'),
    ('dim2017_1540230_d111354279_i4623', '100,3'),
    ('dim2018_1540283_d111354279_i5080', '102,7'),
    ('dim2018_1540282_d111354279_i5092', '103,2'),
    ('dim2018_1540236_d111354279_i5098', '102,7'),
    ('dim2018_1540229_d111354279_i5095', '103,2'),
    ('dim2018_1540235_d111354279_i5097', '103,5'),
    ('dim2018_1540234_d111354279_i5096', '102,1'),
    ('dim2018_1540233_d111354279_i5387', '103,5'),
    ('dim2018_1540228_d111354279_i5386', '102,8'),
    ('dim2018_1540276_d111354279_i5389', '102,3'),
    ('dim2018_1540273_d111354279_i5388', '105,3'),
    ('dim2018_1540272_d111354279_i5071', '104,4'),
    ('dim2018_1540230_d111354279_i5208', '106,4'),
    ('dim2019_1540283_d111354279_i5665', '102,7'),
    ('dim2019_1540282_d111354279_i5670', '104,2'),
    ('dim2019_1540236_d111354279_i5669', '102,7'),
    ('dim2019_1540229_d111354279_i5666', '105,2'),
    ('dim2019_1540235_d111354279_i5668', '101'),
    ('dim2019_1540234_d111354279_i5667', '103,2'),
    ('dim2019_1540233_d111354279_i5673', '104,3'),
    ('dim2019_1540228_d111354279_i5671', '103,9'),
    ('dim2019_1540276_d111354279_i5676', '105'),
    ('dim2019_1540273_d111354279_i5675', '104,4'),
    ('dim2019_1540272_d111354279_i5674', '101,5'),
    ('dim2019_1540230_d111354279_i5672', '102,6'),
    ('dim2020_1540283_d111354279_i6123', '101,8'),
    ('dim2020_1540282_d111354279_i6135', '104,3'),
    ('dim2020_1540236_d111354279_i6134', '101,3'),
    ('dim2020_1540229_d111354279_i6137', '94,7'),
    ('dim2020_1540235_d111354279_i6141', '91,3'),
    ('dim2020_1540234_d111354279_i6140', '92,2'),
    ('dim2020_1540233_d111354279_i6139', '94'),
    ('dim2020_1540228_d111354279_i6136', '95,3'),
    ('dim2020_1540276_d111354279_i6144', '97'),
    ('dim2020_1540273_d111354279_i6143', '95,1'),
    ('dim2020_1540272_d111354279_i6142', '98,7'),
    ('dim2020_1540230_d111354279_i6138', '102,4'),
    ('dim2021_1540283_d111354279_i7130', '97,5'),
    ('dim2021_1540282_d111354279_i7191', '96,6'),
    ('dim2021_1540236_d111354279_i7198', '101,7'),
    ('dim2021_1540229_d111354279_i7193', '107,3'),
    ('dim2021_1540235_d111354279_i7197', '111,6'),
    ('dim2021_1540234_d111354279_i7196', '110,9'),
    ('dim2021_1540233_d111354279_i7195', '107,2'),
    ('dim2021_1540228_d111354279_i7192', '104,6'),
    ('dim2021_1540276_d111354279_i7201', '106,1'),
    ('dim2021_1540273_d111354279_i7200', '106,7'),
    ('dim2021_1540272_d111354279_i7199', '106,6'),
    ('dim2021_1540230_d111354279_i7194', '107,6'),
    ('dim2022_1540283_d111354279_i7598', '108,6'),
    ('dim2022_1540282_d111354279_i7642', '106,6'),
    ('dim2022_1540236_d111354279_i7641', '103,7'),
    ('dim2022_1540229_d111354279_i7647', '98'),
    ('dim2022_1540235_d111354279_i7650', '98'),
    ('dim2022_1540234_d111354279_i7649', '98,3'),
    ('dim2022_1540233_d111354279_i7648', '99,4'),
    ('dim2022_1540228_d111354279_i7646', '100,3'),
    ('dim2022_1540276_d111354279_i7652', '97,8'),
    ('dim2022_1540273_d111354279_i7651', '98,5'),
    ('dim2022_1540272_d111354279_i7571', '99,8'),
    ('dim2022_1540230_d111354279_i7601', '97,6'),
)

UNEMPLOYMENT_LABELS = {
    'dim58335': '15 лет и старше',
    'dim57831': 'Российская Федерация',
    'dim30611': 'процент',
    'dim0': 'Уровень безработицы (по методологии МОТ)',
}
UNEMPLOYMENT_CELLS = (
    ('dim2017_1540222_d66869269_i3766', '5,5'),
    ('dim2017_1540224_d66869269_i4794', '5,2'),
    ('dim2017_1540226_d66869269_i4901', '5'),
    ('dim2017_1540227_d66869269_i5049', '5,1'),
    ('dim2017_1558883_d66869269_i2189', '5,2'),
    ('dim2018_1540222_d66869269_i3767', '5,1'),
    ('dim2018_1540224_d66869269_i5435', '4,8'),
    ('dim2018_1540226_d66869269_i5525', '4,6'),
    ('dim2018_1540227_d66869269_i5210', '4,8'),
    ('dim2018_1558883_d66869269_i2184', '4,8'),
    ('dim2019_1540222_d66869269_i3768', '4,8'),
    ('dim2019_1540224_d66869269_i5900', '4,6'),
    ('dim2019_1540226_d66869269_i5908', '4,4'),
    ('dim2019_1540227_d66869269_i5909', '4,6'),
    ('dim2019_1558883_d66869269_i2185', '4,6'),
    ('dim2020_1540222_d66869269_i3769', '4,6'),
    ('dim2020_1540224_d66869269_i6179', '6'),
    ('dim2020_1540226_d66869269_i6180', '6,3'),
    ('dim2020_1540227_d66869269_i6181', '6,1'),
    ('dim2020_1558883_d66869269_i2195', '5,8'),
    ('dim2021_1540222_d66869269_i3770', '5,6'),
    ('dim2021_1540224_d66869269_i7340', '5'),
    ('dim2021_1540226_d66869269_i7452', '4,4'),
    ('dim2021_1540227_d66869269_i7453', '4,3'),
    ('dim2021_1558883_d66869269_i2180', '4,8'),
    ('dim2022_1540222_d66869269_i5130', '4,2'),
    ('dim2022_1540224_d66869269_i7741', '4'),
    ('dim2022_1540226_d66869269_i7742', '3,9'),
    ('dim2022_1540227_d66869269_i7743', '3,8'),
    ('dim2022_1558883_d66869269_i2187', '4'),
)

def _grid(labels: dict[str, str], cells: tuple[tuple[str, str], ...]) -> bytes:
    row = dict(labels)
    row.update(cells)
    return json.dumps({'results': [row], '__count': '1'}, ensure_ascii=False).encode()


INDUSTRY_GRID = _grid(INDUSTRY_LABELS, INDUSTRY_CELLS)
UNEMPLOYMENT_GRID = _grid(UNEMPLOYMENT_LABELS, UNEMPLOYMENT_CELLS)
EMPTY_GRID = b'{"results": [], "__count": "0"}'
INDUSTRY_PASSPORT = (
    '<div class="pass_lbl">Последнее обновление данных</div>\n'
    '<p>01.10.2026</p>'
).encode()
UNEMPLOYMENT_PASSPORT = (
    '<div class="pass_lbl">Последнее обновление данных</div>\n'
    '<p>03.09.2026</p>'
).encode()

class _FakeTransport:
    def __init__(self, dispatcher) -> None:
        self._dispatcher = dispatcher
        self.calls: list[tuple[str, bytes | None]] = []

    def request(self, url, *, data=None, headers=None):
        del headers
        self.calls.append((url, data))
        return self._dispatcher(url, data)


def _clock() -> datetime:
    return FETCHED_AT


def _industry_transport(grid: bytes = INDUSTRY_GRID, passport: bytes = INDUSTRY_PASSPORT, grid_status: int = 200):
    def dispatch(url: str, data: bytes | None) -> HttpResult:
        if data is None:
            return HttpResult(url=url, status=200, body=passport)
        if grid_status != 200:
            return HttpResult(url=url, status=grid_status, body=b"")
        text = data.decode("ascii")
        if "selectedFilterIds=3_2025" in text and "selectedFilterIds=3_2017" not in text:
            return HttpResult(url=url, status=200, body=EMPTY_GRID)
        return HttpResult(url=url, status=200, body=grid)

    return _FakeTransport(dispatch)


def _unemployment_transport(passport: bytes = UNEMPLOYMENT_PASSPORT):
    def dispatch(url: str, data: bytes | None) -> HttpResult:
        if data is None:
            return HttpResult(url=url, status=200, body=passport)
        return HttpResult(url=url, status=200, body=UNEMPLOYMENT_GRID)

    return _FakeTransport(dispatch)


def _observations(source):
    parsed = []
    for artifact in source.last_artifacts:
        parsed.extend(source.parse(artifact, source.raw_for(artifact)))
    parsed.sort(key=lambda item: (item.period_end, item.period or ""))
    return parsed


def test_industrial_production_probe_is_partial() -> None:
    transport = _industry_transport()
    source = RosstatIndustrialProductionSource(transport, now=_clock)
    report = source.discover()
    observations = _observations(source)
    primary, recent = source.last_artifacts

    assert report.status is AdapterStatus.PARTIAL
    assert report.earliest == date(2017, 1, 31)
    assert report.latest == date(2022, 12, 31)
    assert source.last_http_status == 200
    assert source.recent_http_status == 200
    assert source.passport_http_status == 200
    assert source.publication_status is AdapterStatus.PARTIAL
    assert source.publication_timestamp_present is False
    assert len(observations) == 72
    assert observations[0].period == "2017-01"
    assert observations[0].period_end == date(2017, 1, 31)
    assert observations[0].value == 106.6
    assert observations[-1].period == "2022-12"
    assert observations[-1].period_end == date(2022, 12, 31)
    assert observations[-1].value == 97.6
    assert all(item.quality_errors() == () for item in observations)
    assert all("published_at" not in item.extra for item in observations)
    assert {item.period[:4] for item in observations} == {"2017", "2018", "2019", "2020", "2021", "2022"}
    assert primary.fetch_status is FetchStatus.OK
    assert primary.entity_identifiers["indicator_id"] == "57806"
    assert primary.entity_identifiers["data_updated_on"] == "2026-10-01"
    assert primary.entity_identifiers["publication_timestamp_present"] == "false"
    assert primary.published_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert primary.published_at_precision is PublishedAtPrecision.DATE_ONLY
    assert primary.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert primary.chronology_errors() == ()
    assert "http_status=200" in primary.limitations
    assert "grid_last_year=2022" in primary.limitations
    assert "requested_through=2024" in primary.limitations
    assert "datagrid_publication_timestamp_absent" in primary.limitations
    assert "passport_last_update_date_only" in primary.limitations
    assert "sdmx_download_not_called" in primary.limitations
    assert recent.fetch_status is FetchStatus.EMPTY
    assert "window_empty" in recent.limitations
    assert recent.entity_identifiers["window_start"] == "2025"
    posts = [data for url, data in transport.calls if data is not None]
    pages = [url for url, data in transport.calls if data is None]
    assert len(posts) == 2
    assert pages == [INDUSTRY_PAGE_URL]
    first = posts[0].decode("ascii")
    second = posts[1].decode("ascii")
    assert posts[0] and transport.calls[0][0] == INDUSTRY_GRID_URL
    assert first.count("selectedFilterIds=3_") == 8
    assert first.count("selectedFilterIds=33560_") == 12
    assert "selectedFilterIds=57940_1751132" in first
    assert "selectedFilterIds=57937_1704141" in first
    assert "selectedFilterIds=3_2023" in first
    assert "selectedFilterIds=3_2025" not in first
    assert second.count("selectedFilterIds=3_") == 2
    assert "selectedFilterIds=3_2025" in second
    assert "selectedFilterIds=3_2026" in second
    assert "token=" not in first
    assert "csrf" not in first.lower()
    assert "api_key" not in first


def test_industry_sample_limit_keeps_latest_months() -> None:
    transport = _industry_transport()
    source = RosstatIndustrialProductionSource(transport, now=_clock)
    artifact = source.fetch_sample(limit=10)[0]
    observations = source.validate(source.parse(artifact, source.last_raw))

    assert len(observations) == 10
    assert observations[0].period == "2022-03"
    assert observations[0].value == 103.7
    assert observations[-1].period == "2022-12"
    assert observations[-1].value == 97.6
    assert all(item.quality_status is RecordQuality.ACCEPTED for item in observations)


def test_industry_range_keeps_one_month() -> None:
    transport = _industry_transport()
    source = RosstatIndustrialProductionSource(transport, now=_clock)
    artifact = source.fetch_range(start=date(2022, 3, 1), end=date(2022, 3, 31), limit=100)[0]
    observations = source.parse(artifact, source.last_raw)

    assert len(observations) == 1
    assert observations[0].period_end == date(2022, 3, 31)
    assert observations[0].value == 103.7
    assert observations[0].unit == "percent"
    assert observations[0].evidence is not None


def test_industry_explicit_zero_is_marked() -> None:
    raw = json.dumps(
        {
            "results": [
                {
                    "dim57940": INDUSTRY_LABELS["dim57940"],
                    "dim57937": "Отчетный месяц к соответствующему месяцу предыдущего года",
                    "dim57831": "Российская Федерация",
                    "dim2017_1540283_d1_i1": "0",
                }
            ]
        },
        ensure_ascii=False,
    ).encode()
    transport = _industry_transport(grid=raw)
    source = RosstatIndustrialProductionSource(transport, now=_clock)
    artifact = source.fetch_sample(limit=5)[0]
    observations = source.parse(artifact, source.last_raw)

    assert len(observations) == 1
    assert observations[0].value == 0
    assert "explicit_zero" in observations[0].limitations
    assert observations[0].quality_errors() == ()


def test_unemployment_probe_stops_in_2022() -> None:
    transport = _unemployment_transport()
    source = RosstatUnemploymentSource(transport, now=_clock)
    report = source.discover()
    observations = _observations(source)
    artifact = source.last_artifacts[0]
    annual = next(item for item in observations if item.period == "2022")
    fourth = next(item for item in observations if item.period == "2022-Q4")

    assert report.status is AdapterStatus.PARTIAL
    assert report.earliest == date(2017, 3, 31)
    assert report.latest == date(2022, 12, 31)
    assert len(source.last_artifacts) == 1
    assert source.last_http_status == 200
    assert source.recent_http_status is None
    assert source.passport_http_status == 200
    assert source.publication_status is AdapterStatus.PARTIAL
    assert source.publication_timestamp_present is False
    assert len(observations) == 30
    assert observations[0].period == "2017-Q1"
    assert observations[0].value == 5.5
    assert annual.value == 4.0
    assert annual.period_end == date(2022, 12, 31)
    assert annual.extra["frequency"] == "year"
    assert fourth.value == 3.8
    assert fourth.extra["frequency"] == "quarter"
    assert artifact.entity_identifiers["indicator_id"] == "43062"
    assert artifact.entity_identifiers["data_updated_on"] == "2026-09-03"
    assert artifact.published_at == datetime(2026, 9, 3, tzinfo=UTC)
    assert artifact.published_at_precision is PublishedAtPrecision.DATE_ONLY
    assert artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert artifact.chronology_errors() == ()
    assert "grid_last_year=2022" in artifact.limitations
    assert "requested_through=2026" in artifact.limitations
    assert all(item.quality_errors() == () for item in observations)
    posts = [data for _url, data in transport.calls if data is not None]
    assert len(posts) == 1
    assert transport.calls[0][0] == UNEMPLOYMENT_GRID_URL
    assert transport.calls[1][0] == UNEMPLOYMENT_PAGE_URL
    body = posts[0].decode("ascii")
    assert body.count("selectedFilterIds=3_") == 10
    assert body.count("selectedFilterIds=33560_") == 5
    assert "selectedFilterIds=58335_1788561" in body
    assert "selectedFilterIds=0_43062" in body
    assert "token=" not in body
    assert "csrf" not in body.lower()


def test_passport_without_a_date_blocks_publication_metadata() -> None:
    transport = _industry_transport(passport=b"<html><p>no update label</p></html>")
    source = RosstatIndustrialProductionSource(transport, now=_clock)
    report = source.discover()
    artifact = source.last_artifacts[0]

    assert report.status is AdapterStatus.PARTIAL
    assert len(_observations(source)) == 72
    assert source.publication_status is AdapterStatus.BLOCKED
    assert source.publication_timestamp_present is False
    assert artifact.published_at is None
    assert artifact.published_at_precision is PublishedAtPrecision.UNKNOWN
    assert artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert "publication_metadata_absent" in artifact.limitations


def test_forbidden_grid_is_blocked_and_invents_no_rows() -> None:
    transport = _industry_transport(grid_status=403)
    source = RosstatIndustrialProductionSource(transport, now=_clock)
    report = source.discover()

    assert report.status is AdapterStatus.BLOCKED
    assert report.earliest is None
    assert source.last_http_status == 403
    assert source.last_artifacts[0].fetch_status is FetchStatus.FORBIDDEN
    assert _observations(source) == []
    assert source.publication_status is AdapterStatus.PARTIAL
    assert source.publication_timestamp_present is False


def test_datagrid_timestamp_stays_research_only() -> None:
    payload = json.loads(INDUSTRY_GRID.decode("utf-8"))
    payload["published_at"] = "2026-10-01T15:04:05Z"
    stamped = json.dumps(payload, ensure_ascii=False).encode()
    transport = _industry_transport(grid=stamped)
    source = RosstatIndustrialProductionSource(transport, now=_clock)
    source.discover()
    artifact = source.last_artifacts[0]

    assert source.publication_timestamp_present is True
    assert source.publication_status is AdapterStatus.PARTIAL
    assert artifact.published_at == datetime(2026, 10, 1, 15, 4, 5, tzinfo=UTC)
    assert artifact.published_at_precision is PublishedAtPrecision.TIMESTAMP
    assert artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert "datagrid_publication_timestamp" in artifact.limitations
    assert len(_observations(source)) == 72


def test_assess_publication_reads_only_the_passport_date() -> None:
    facts = assess_publication(
        grid_bodies=(INDUSTRY_GRID, EMPTY_GRID),
        passport_body=INDUSTRY_PASSPORT,
        passport_status=200,
    )

    assert facts.timestamp_present is False
    assert facts.status is AdapterStatus.PARTIAL
    assert facts.pit_quality is PitQuality.RESEARCH_ONLY
    assert facts.data_updated_on == date(2026, 10, 1)
    assert facts.precision is PublishedAtPrecision.DATE_ONLY
    assert "datagrid_keys=__count,results" in facts.limitations
