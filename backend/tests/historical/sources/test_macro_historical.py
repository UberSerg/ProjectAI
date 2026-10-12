"""Offline tests for ROS-01, INT-01, and INT-02. No live HTTP."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from app.modules.historical.domain.evidence import AdapterStatus, FetchStatus, RecordQuality
from app.modules.historical.sources.macro.eia import (
    NATURAL_GAS_URL,
    PETROLEUM_URL,
    EiaNaturalGasSource,
    EiaPetroleumSource,
)
from app.modules.historical.sources.macro.rosstat_cpi import SOURCE_URL, RosstatCpiSource
from app.modules.historical.sources.macro.transport import HttpResult

FETCHED_AT = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)

# Exact EIA body returned without an API key on 2026-10-12.
EIA_FORBIDDEN = (
    b'{\n  "error": {\n    "code": "API_KEY_MISSING",\n'
    b'    "message": "No api_key was supplied.  Please register for one at '
    b'https://www.eia.gov/opendata/register.php"\n  }\n}'
)

# Official EMISS cells for indicator 31074, national CPI, month-on-month.
_CPI_CELLS = (
    ("dim2017_1540283_1704142_d55100230_i4596", "100,62"),
    ("dim2017_1540282_1704142_d55100230_i4625", "100,22"),
    ("dim2017_1540236_1704142_d55100230_i4630", "100,13"),
    ("dim2017_1540229_1704142_d55100230_i4627", "100,33"),
    ("dim2017_1540235_1704142_d55100230_i4629", "100,37"),
    ("dim2017_1540234_1704142_d55100230_i4628", "100,61"),
    ("dim2017_1540233_1704142_d55100230_i4632", "100,07"),
    ("dim2017_1540228_1704142_d55100230_i4631", "99,46"),
    ("dim2017_1540276_1704142_d55100230_i4635", "99,85"),
    ("dim2017_1540273_1704142_d55100230_i4634", "100,2"),
    ("dim2017_1540272_1704142_d55100230_i4633", "100,22"),
    ("dim2017_1540230_1704142_d55100230_i4623", "100,42"),
    ("dim2018_1540283_1704142_d55100230_i5080", "100,31"),
    ("dim2018_1540282_1704142_d55100230_i5092", "100,21"),
    ("dim2018_1540236_1704142_d55100230_i5098", "100,29"),
    ("dim2018_1540229_1704142_d55100230_i5095", "100,38"),
    ("dim2018_1540235_1704142_d55100230_i5097", "100,38"),
    ("dim2018_1540234_1704142_d55100230_i5096", "100,49"),
    ("dim2018_1540233_1704142_d55100230_i5387", "100,27"),
    ("dim2018_1540228_1704142_d55100230_i5386", "100,01"),
    ("dim2018_1540276_1704142_d55100230_i5389", "100,16"),
    ("dim2018_1540273_1704142_d55100230_i5388", "100,35"),
    ("dim2018_1540272_1704142_d55100230_i5071", "100,5"),
    ("dim2018_1540230_1704142_d55100230_i5208", "100,84"),
    ("dim2019_1540283_1704142_d55100230_i5665", "101,01"),
    ("dim2019_1540282_1704142_d55100230_i5670", "100,44"),
    ("dim2019_1540236_1704142_d55100230_i5669", "100,32"),
    ("dim2019_1540229_1704142_d55100230_i5666", "100,29"),
    ("dim2019_1540235_1704142_d55100230_i5668", "100,34"),
    ("dim2019_1540234_1704142_d55100230_i5667", "100,04"),
    ("dim2019_1540233_1704142_d55100230_i5673", "100,2"),
    ("dim2019_1540228_1704142_d55100230_i5671", "99,76"),
    ("dim2019_1540276_1704142_d55100230_i5676", "99,84"),
    ("dim2019_1540273_1704142_d55100230_i5675", "100,13"),
    ("dim2019_1540272_1704142_d55100230_i5674", "100,28"),
    ("dim2019_1540230_1704142_d55100230_i5672", "100,36"),
    ("dim2020_1540283_1704142_d55100230_i6123", "100,4"),
    ("dim2020_1540282_1704142_d55100230_i6135", "100,33"),
    ("dim2020_1540236_1704142_d55100230_i6134", "100,55"),
    ("dim2020_1540229_1704142_d55100230_i6137", "100,83"),
    ("dim2020_1540235_1704142_d55100230_i6141", "100,27"),
    ("dim2020_1540234_1704142_d55100230_i6140", "100,22"),
    ("dim2020_1540233_1704142_d55100230_i6139", "100,35"),
    ("dim2020_1540228_1704142_d55100230_i6136", "99,96"),
    ("dim2020_1540276_1704142_d55100230_i6144", "99,93"),
    ("dim2020_1540273_1704142_d55100230_i6143", "100,43"),
    ("dim2020_1540272_1704142_d55100230_i6142", "100,71"),
    ("dim2020_1540230_1704142_d55100230_i6138", "100,83"),
    ("dim2021_1540283_1704142_d55100230_i7130", "100,67"),
    ("dim2021_1540282_1704142_d55100230_i7191", "100,78"),
    ("dim2021_1540236_1704142_d55100230_i7198", "100,66"),
    ("dim2021_1540229_1704142_d55100230_i7193", "100,58"),
    ("dim2021_1540235_1704142_d55100230_i7197", "100,74"),
    ("dim2021_1540234_1704142_d55100230_i7196", "100,69"),
    ("dim2021_1540233_1704142_d55100230_i7195", "100,31"),
    ("dim2021_1540228_1704142_d55100230_i7192", "100,17"),
    ("dim2021_1540276_1704142_d55100230_i7201", "100,6"),
    ("dim2021_1540273_1704142_d55100230_i7200", "101,11"),
    ("dim2021_1540272_1704142_d55100230_i7199", "100,96"),
    ("dim2021_1540230_1704142_d55100230_i7194", "100,82"),
    ("dim2022_1540283_1704142_d55100230_i7598", "100,99"),
    ("dim2022_1540282_1704142_d55100230_i7642", "101,17"),
    ("dim2022_1540236_1704142_d55100230_i7641", "107,61"),
    ("dim2022_1540229_1704142_d55100230_i7647", "101,56"),
    ("dim2022_1540235_1704142_d55100230_i7650", "100,12"),
    ("dim2022_1540234_1704142_d55100230_i7649", "99,65"),
    ("dim2022_1540233_1704142_d55100230_i7648", "99,61"),
    ("dim2022_1540228_1704142_d55100230_i7646", "99,48"),
    ("dim2022_1540276_1704142_d55100230_i7652", "100,05"),
    ("dim2022_1540273_1704142_d55100230_i7651", "100,18"),
    ("dim2022_1540272_1704142_d55100230_i7571", "100,37"),
    ("dim2022_1540230_1704142_d55100230_i7601", "100,78"),
)


def _rosstat_cpi() -> bytes:
    row = {
        "dim57831": "Российская Федерация",
        "dim58273": "Все товары и услуги",
        "dim30611": "процент",
        "dim0": "Индексы потребительских цен на товары и услуги",
    }
    row.update(dict(_CPI_CELLS))
    return json.dumps({"results": [row], "__count": "1"}, ensure_ascii=False).encode("utf-8")


class _FakeTransport:
    def __init__(self, result: HttpResult) -> None:
        self.result = result
        self.calls: list[tuple[str, bytes | None]] = []

    def request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        del headers
        self.calls.append((url, data))
        return self.result


def _clock() -> datetime:
    return FETCHED_AT


def test_rosstat_cpi_parses_verified_national_slice() -> None:
    transport = _FakeTransport(HttpResult(url=SOURCE_URL, status=200, body=_rosstat_cpi()))
    source = RosstatCpiSource(transport, now=_clock)
    report = source.discover()
    artifact = source.fetch_sample(limit=120)[0]
    observations = source.parse(artifact, source.last_raw)

    assert report.status is AdapterStatus.PARTIAL
    assert report.earliest == date(2017, 1, 31)
    assert report.latest == date(2022, 12, 31)
    assert source.last_http_status == 200
    assert "http_status=200" in artifact.limitations
    assert artifact.fetch_status is FetchStatus.OK
    assert artifact.first_observed_at == FETCHED_AT
    assert artifact.chronology_errors() == ()
    assert len(observations) == 72
    assert observations[0].period_end == date(2017, 1, 31)
    assert observations[0].value == 100.62
    assert observations[-1].period_end == date(2022, 12, 31)
    assert observations[-1].value == 100.78
    march_2022 = next(item for item in observations if item.period == "2022-03")
    assert march_2022.value == 107.61
    assert all(item.quality_errors() == () for item in observations)
    body = transport.calls[0][1] or b""
    text = body.decode("ascii")
    assert text.count("selectedFilterIds=3_") == 10
    assert text.count("selectedFilterIds=33560_") == 12
    assert "token=" not in text
    assert "api_key" not in text


def test_rosstat_sample_limit_keeps_latest_observations() -> None:
    transport = _FakeTransport(HttpResult(url=SOURCE_URL, status=200, body=_rosstat_cpi()))
    source = RosstatCpiSource(transport, now=_clock)
    artifact = source.fetch_sample(limit=30)[0]
    observations = source.validate(source.parse(artifact, source.last_raw))

    assert len(observations) == 30
    assert observations[0].period_end == date(2020, 7, 31)
    assert observations[0].value == 100.35
    assert observations[-1].period_end == date(2022, 12, 31)
    assert all(item.quality_status is RecordQuality.ACCEPTED for item in observations)


def test_rosstat_range_keeps_one_month() -> None:
    transport = _FakeTransport(HttpResult(url=SOURCE_URL, status=200, body=_rosstat_cpi()))
    source = RosstatCpiSource(transport, now=_clock)
    artifact = source.fetch_range(start=date(2022, 3, 1), end=date(2022, 3, 31), limit=120)[0]
    observations = source.parse(artifact, source.last_raw)

    assert len(observations) == 1
    assert observations[0].period_end == date(2022, 3, 31)
    assert observations[0].value == 107.61
    assert observations[0].unit == "percent"
    assert observations[0].evidence is not None


def test_explicit_zero_is_marked() -> None:
    raw = json.dumps(
        {
            "results": [
                {
                    "dim57831": "Российская Федерация",
                    "dim58273": "Все товары и услуги",
                    "dim2017_1540283_1704142_d1_i1": "0",
                }
            ]
        }
    ).encode()
    transport = _FakeTransport(HttpResult(url=SOURCE_URL, status=200, body=raw))
    source = RosstatCpiSource(transport, now=_clock)
    artifact = source.fetch_sample(limit=5)[0]
    observations = source.parse(artifact, source.last_raw)

    assert len(observations) == 1
    assert observations[0].value == 0
    assert "explicit_zero" in observations[0].limitations
    assert observations[0].quality_errors() == ()


def test_eia_petroleum_is_blocked_without_a_key() -> None:
    transport = _FakeTransport(HttpResult(url=PETROLEUM_URL, status=403, body=EIA_FORBIDDEN))
    source = EiaPetroleumSource(transport, now=_clock)
    report = source.discover()
    artifact = source.fetch_sample()[0]
    observations = source.parse(artifact, source.last_raw)

    assert report.status is AdapterStatus.BLOCKED
    assert source.last_http_status == 403
    assert artifact.fetch_status is FetchStatus.FORBIDDEN
    assert artifact.source_url == PETROLEUM_URL
    assert artifact.first_observed_at == FETCHED_AT
    assert "http_status=403" in artifact.limitations
    assert "error_code=API_KEY_MISSING" in artifact.limitations
    assert observations == ()
    assert "api_key=" not in transport.calls[0][0]
    assert transport.calls[0][1] is None


def test_eia_natural_gas_is_blocked_without_a_key() -> None:
    transport = _FakeTransport(HttpResult(url=NATURAL_GAS_URL, status=403, body=EIA_FORBIDDEN))
    source = EiaNaturalGasSource(transport, now=_clock)
    report = source.discover()
    artifact = source.fetch_sample()[0]
    observations = source.parse(artifact, source.last_raw)

    assert report.status is AdapterStatus.BLOCKED
    assert source.last_http_status == 403
    assert artifact.fetch_status is FetchStatus.FORBIDDEN
    assert artifact.source_url == NATURAL_GAS_URL
    assert "http_status=403" in artifact.limitations
    assert "error_code=API_KEY_MISSING" in artifact.limitations
    assert observations == ()
    assert "RNGWHHD" in artifact.source_url
    assert "api_key=" not in transport.calls[0][0]
