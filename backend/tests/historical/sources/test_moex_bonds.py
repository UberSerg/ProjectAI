"""Offline MOEX-08 bond board sample. HTTP is the saved fixture, not the network."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    HistoricalArtifact,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.moex_bonds.source import (
    CATALOGUE_CAP,
    ISS_HISTORY_PIT_EVIDENCE,
    MAX_SESSIONS,
    SOURCE_ID,
    MoexBondsSource,
    bounded_weekday_window,
    catalogue_rows,
)
from app.modules.investment.domain.currency import resolve_nominal_currency
from app.modules.investment.infrastructure.moex_bonds import BOARDS, MoexBondClient

PACKAGE = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "modules"
    / "historical"
    / "sources"
    / "moex_bonds"
)
FIXTURES = PACKAGE / "fixtures"
FETCHED_AT = datetime(2026, 10, 13, 5, 28, tzinfo=UTC)
FORBIDDEN = (
    "prospective_captures",
    "signal_outputs",
    "committee_decisions",
    "shadow.orders",
    "broker.executions",
    "polza",
)


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _note() -> dict[str, object]:
    return json.loads((PACKAGE / "live_probe.json").read_text(encoding="utf-8"))


def _response(url: str, body: bytes, *, status: int = 200, content_type: str = "application/json") -> httpx.Response:
    return httpx.Response(
        status,
        content=body,
        headers={"content-type": content_type},
        request=httpx.Request("GET", url),
    )


class _FakeHttp:
    def __init__(self, handler) -> None:  # noqa: ANN001
        self.handler = handler
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, params: dict[str, object] | None = None) -> httpx.Response:
        self.calls.append((url, dict(params or {})))
        return self.handler(url, params or {})


def _source(http: _FakeHttp) -> MoexBondsSource:
    return MoexBondsSource(http=http, clock=lambda: FETCHED_AT)


def _live_handler(url: str, params: dict[str, object]) -> httpx.Response:
    note = _note()
    board = str(note["board"])
    secid = str(note["secid"])
    if url.endswith(f"/boards/{board}/securities.json") and "/history/" not in url:
        assert params.get("securities.start", 0) in (0, "0")
        return _response(url, _load(f"{board.lower()}_securities.json"))
    if f"/securities/{secid}.json" in url and "/history/" in url:
        assert params.get("start") in (0, "0")
        return _response(url, _load(f"history_{secid}.json"))
    raise AssertionError(url)


def _catalogue_artifact(raw: bytes, *, board: str = "TQOB") -> HistoricalArtifact:
    return HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=f"https://iss.moex.com/iss/engines/stock/markets/bonds/boards/{board}/securities.json",
        external_document_id=f"{board}:page1",
        document_type="instrument_catalogue",
        content_hash=hashlib.sha256(raw).hexdigest(),
        parser_version="moex_bonds_catalogue_v1",
        fetch_status=FetchStatus.OK,
        first_observed_at=FETCHED_AT,
        entity_identifiers={"board": board, "market": "bonds", "engine": "stock"},
        published_at=None,
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
    )


def _history_artifact(raw: bytes, *, secid: str = "TEST") -> HistoricalArtifact:
    return HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url="https://iss.moex.com/iss/history/example.json",
        external_document_id=f"TQOB:{secid}:sample",
        document_type="eod_candle_series",
        content_hash=hashlib.sha256(raw).hexdigest(),
        parser_version="moex_bonds_history_v1",
        fetch_status=FetchStatus.OK,
        first_observed_at=FETCHED_AT,
        entity_identifiers={"secid": secid, "board": "TQOB", "market": "bonds"},
        published_at=None,
        published_at_precision=PublishedAtPrecision.PERIOD_ONLY,
        historical_availability_evidence=ISS_HISTORY_PIT_EVIDENCE,
        historical_pit_quality=PitQuality.PIT_PROXY,
    )


def _assert_no_yield(observations) -> None:  # noqa: ANN001
    for obs in observations:
        assert "yield" not in obs.metric_id
        assert all("yield" not in str(key).lower() for key in obs.extra)
        assert "yield" not in json.dumps(obs.extra).lower()


def test_weekday_window_caps_the_sample_at_thirty_sessions() -> None:
    window = bounded_weekday_window(date(2020, 1, 1), date(2026, 10, 13), limit=100)
    assert window == (date(2026, 9, 2), date(2026, 10, 13))
    start, end = window
    weekdays = 0
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            weekdays += 1
        cursor += timedelta(days=1)
    assert weekdays == MAX_SESSIONS == 30


def test_package_does_not_name_forbidden_write_targets() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE.glob("*.py"))
    lowered = text.lower()
    for token in FORBIDDEN:
        assert token not in lowered


def test_live_probe_note_matches_saved_fixtures() -> None:
    note = _note()
    assert set(note) == {
        "board",
        "boards_requested",
        "catalogue_cap",
        "catalogue_content_type",
        "catalogue_http_status",
        "catalogue_response_rows",
        "catalogue_rows",
        "catalogue_sha256",
        "catalogue_url",
        "date_from",
        "date_to",
        "faceunit",
        "first_trade",
        "history_cap",
        "history_content_type",
        "history_cursor_total",
        "history_http_status",
        "history_response_rows",
        "history_rows",
        "history_sha256",
        "history_url",
        "isin",
        "last_trade",
        "live_probe",
        "pit_catalogue",
        "pit_history",
        "probed_on",
        "secid",
        "task",
        "yields_computed",
    }
    assert note["task"] == "MOEX-08"
    assert note["live_probe"] is True
    assert note["probed_on"] == "2026-10-13"
    assert note["board"] in BOARDS
    assert note["boards_requested"] == [note["board"]]
    assert note["catalogue_cap"] == CATALOGUE_CAP
    assert note["history_cap"] == MAX_SESSIONS
    assert note["catalogue_http_status"] == 200
    assert note["history_http_status"] == 200
    assert "json" in str(note["catalogue_content_type"])
    assert "json" in str(note["history_content_type"])
    assert note["yields_computed"] is False
    assert note["pit_catalogue"] == PitQuality.RESEARCH_ONLY.value
    assert note["pit_history"] == PitQuality.PIT_PROXY.value
    assert note["date_from"] == "2026-09-02"
    assert note["date_to"] == "2026-10-13"
    catalogue = json.loads(_load(f"{str(note['board']).lower()}_securities.json"))
    history = json.loads(_load(f"history_{note['secid']}.json"))
    assert note["catalogue_response_rows"] == len(catalogue["securities"]["data"])
    assert note["catalogue_rows"] == len(catalogue_rows(catalogue)) <= CATALOGUE_CAP
    assert note["history_response_rows"] == len(history["history"]["data"])
    assert 1 <= int(note["history_rows"]) <= MAX_SESSIONS
    catalogue_bytes = _load(f"{str(note['board']).lower()}_securities.json")
    history_bytes = _load(f"history_{note['secid']}.json")
    assert hashlib.sha256(catalogue_bytes).hexdigest() == note["catalogue_sha256"]
    assert hashlib.sha256(history_bytes).hexdigest() == note["history_sha256"]
    columns = history["history"]["columns"]
    assert any("YIELD" in str(column) for column in columns)
    first = dict(zip(catalogue["securities"]["columns"], catalogue["securities"]["data"][0], strict=False))
    assert note["secid"] == first["SECID"]
    assert note["isin"] == first["ISIN"]
    assert note["faceunit"] == first["FACEUNIT"]
    trades = [row[columns.index("TRADEDATE")] for row in history["history"]["data"]]
    assert note["first_trade"] == trades[0]
    assert note["last_trade"] == trades[-1]


def test_replay_keeps_trade_date_as_period_and_does_not_compute_yield() -> None:
    note = _note()
    http = _FakeHttp(_live_handler)
    source = _source(http)

    first = source.discover()
    second = source.discover()
    catalogue = source.catalogue_artifact
    assert catalogue is not None
    catalogue_obs = source.validate(source.parse(catalogue, source.raw_for(catalogue)))
    artifacts = source.fetch_sample(limit=100)
    coverage = source.inspect_coverage()

    assert isinstance(source._bond, MoexBondClient)
    assert first.status == AdapterStatus.READY
    assert second is first
    assert source.boards_requested == [note["board"]]
    assert [url for url, _params in http.calls][0] == note["catalogue_url"]
    catalogue_params = http.calls[0][1]
    assert catalogue_params["iss.only"] == "securities,marketdata"
    assert catalogue_params["securities.limit"] == 100
    assert catalogue_params["marketdata.limit"] == 100
    assert "securities.start" not in catalogue_params
    assert len(catalogue_obs) == note["catalogue_rows"]
    assert catalogue.source_id == SOURCE_ID
    assert catalogue.first_observed_at == FETCHED_AT
    assert catalogue.published_at is None
    assert catalogue.published_at_precision == PublishedAtPrecision.UNKNOWN
    assert catalogue.historical_pit_quality == PitQuality.RESEARCH_ONLY
    assert catalogue.historical_pit_quality != PitQuality.PIT_VERIFIED
    assert catalogue.chronology_errors() == ()
    assert "id" not in catalogue.entity_identifiers
    _assert_no_yield(catalogue_obs)
    assert catalogue_obs[0].issuer_identity["secid"] == note["secid"]
    assert catalogue_obs[0].issuer_identity["isin"] == note["isin"]
    assert catalogue_obs[0].currency is None
    face = resolve_nominal_currency(face_unit=str(note["faceunit"])).canonical
    assert catalogue_obs[0].extra["face_currency"] == face
    assert catalogue_obs[0].extra["faceunit_raw"] == note["faceunit"]
    security_columns = json.loads(_load(f"{str(note['board']).lower()}_securities.json"))
    security_header = security_columns["securities"]["columns"]
    security_row = dict(zip(security_header, security_columns["securities"]["data"][0], strict=False))
    if str(security_row.get("CURRENCYID") or "").upper() in {"SUR", "RUR"} and face != "RUB":
        assert catalogue_obs[0].extra["face_currency"] != "RUB"

    assert len(artifacts) == 1
    history = artifacts[0]
    assert http.calls[1][0] == note["history_url"]
    assert http.calls[1][1]["from"] == "2026-09-02"
    assert http.calls[1][1]["till"] == "2026-10-13"
    assert http.calls[1][1]["start"] == 0
    assert set(http.calls[1][1]) == {"from", "till", "start", "iss.meta"}
    assert sum("/history/" in url for url, _params in http.calls) == 1
    observations = source.validate(source.parse(history, source.raw_for(history)))
    assert len(observations) == note["history_rows"] <= MAX_SESSIONS
    assert coverage.status == AdapterStatus.READY
    assert coverage.earliest == date.fromisoformat(str(note["first_trade"]))
    assert coverage.latest == date.fromisoformat(str(note["last_trade"]))
    assert history.published_at is None
    assert history.published_at_precision == PublishedAtPrecision.PERIOD_ONLY
    assert history.historical_pit_quality == PitQuality.PIT_PROXY
    assert history.historical_pit_quality != PitQuality.PIT_VERIFIED
    assert history.historical_availability_evidence == ISS_HISTORY_PIT_EVIDENCE
    assert history.event_date == date.fromisoformat(str(note["last_trade"]))
    assert history.period_end == history.event_date
    assert history.first_observed_at == FETCHED_AT
    assert history.chronology_errors() == ()
    assert history.entity_identifiers["secid"] == note["secid"]
    assert history.entity_identifiers["isin"] == note["isin"]
    assert history.entity_identifiers["resolved_via"] == "iss_board_catalogue"
    assert "id" not in history.entity_identifiers
    assert "instrument_id" not in history.entity_identifiers
    _assert_no_yield(observations)
    payload = json.loads(_load(f"history_{note['secid']}.json"))
    columns = payload["history"]["columns"]
    last = dict(zip(columns, payload["history"]["data"][-1], strict=False))
    assert observations[-1].value == float(last["LEGALCLOSEPRICE"])
    assert observations[-1].value != float(last["YIELDCLOSE"])
    assert observations[-1].extra["price_field"] == "LEGALCLOSEPRICE"
    assert observations[-1].unit == "percent_of_face"
    assert observations[-1].currency is None
    assert observations[-1].extra["face_currency"] == face
    assert observations[-1].extra["face_currency"] != "RUB" or face == "RUB"
    assert observations[-1].period == str(last["TRADEDATE"])
    assert "known_at" not in observations[-1].extra


def test_currencyid_sur_does_not_replace_cny_face() -> None:
    raw = json.dumps(
        {
            "securities": {
                "columns": ["SECID", "ISIN", "LOTSIZE", "FACEUNIT", "CURRENCYID", "SHORTNAME"],
                "data": [["SUTEST", "RUTEST", 1, "CNY", "SUR", "test"]],
            },
            "marketdata": {"columns": ["SECID", "YIELD"], "data": [["SUTEST", 15.5]]},
        }
    ).encode()
    source = MoexBondsSource(clock=lambda: FETCHED_AT)
    observations = source.parse(_catalogue_artifact(raw), raw)
    assert observations[0].value == 1.0
    assert observations[0].extra["face_currency"] == "CNY"
    assert observations[0].currency is None
    assert "15.5" not in json.dumps(observations[0].extra)
    _assert_no_yield(observations)


def test_catalogue_parse_keeps_only_the_first_hundred_rows() -> None:
    data = [[f"SU{index:04d}", 1] for index in range(CATALOGUE_CAP + 5)]
    raw = json.dumps({"securities": {"columns": ["SECID", "LOTSIZE"], "data": data}}).encode()
    source = MoexBondsSource(clock=lambda: FETCHED_AT)
    observations = source.parse(_catalogue_artifact(raw), raw)
    assert len(observations) == CATALOGUE_CAP
    assert observations[0].issuer_identity["secid"] == "SU0000"
    assert observations[-1].issuer_identity["secid"] == "SU0099"


def test_yield_without_a_close_is_not_a_price() -> None:
    raw = json.dumps(
        {
            "history": {
                "columns": ["TRADEDATE", "YIELDCLOSE", "CLOSE", "LEGALCLOSEPRICE"],
                "data": [["2026-10-12", 8.36, None, None]],
            }
        }
    ).encode()
    source = MoexBondsSource(clock=lambda: FETCHED_AT)
    assert source.parse(_history_artifact(raw), raw) == ()


def test_history_parse_keeps_the_last_thirty_sessions() -> None:
    rows = []
    for index in range(MAX_SESSIONS + 1):
        traded = date(2026, 8, 1) + timedelta(days=index)
        rows.append([traded.isoformat(), 10 + index, 90 + index, 1])
    raw = json.dumps(
        {
            "history": {
                "columns": ["TRADEDATE", "CLOSE", "LEGALCLOSEPRICE", "VOLUME"],
                "data": rows,
            }
        }
    ).encode()
    source = MoexBondsSource(clock=lambda: FETCHED_AT)
    observations = source.parse(_history_artifact(raw), raw)
    assert len(observations) == MAX_SESSIONS
    assert observations[0].period == rows[1][0]
    assert observations[-1].period == rows[-1][0]
    assert observations[-1].value == float(rows[-1][2])


def test_zero_close_must_be_marked_explicit() -> None:
    raw = json.dumps(
        {
            "history": {
                "columns": ["TRADEDATE", "CLOSE", "LEGALCLOSEPRICE", "VOLUME"],
                "data": [["2026-10-12", 1, 0, 0]],
            }
        }
    ).encode()
    source = MoexBondsSource(clock=lambda: FETCHED_AT)
    parsed = source.parse(_history_artifact(raw), raw)
    assert "explicit_zero" in parsed[0].limitations
    assert source.validate(parsed)[0].quality_status == RecordQuality.ACCEPTED


def test_hash_mismatch_quarantines_observations() -> None:
    raw = json.dumps(
        {"securities": {"columns": ["SECID", "LOTSIZE"], "data": [["SUTEST", 1]]}}
    ).encode()
    artifact = _catalogue_artifact(raw)
    broken = HistoricalArtifact(
        source_id=artifact.source_id,
        source_url=artifact.source_url,
        external_document_id=artifact.external_document_id,
        document_type=artifact.document_type,
        content_hash="0" * 64,
        parser_version=artifact.parser_version,
        fetch_status=artifact.fetch_status,
        first_observed_at=artifact.first_observed_at,
        entity_identifiers=dict(artifact.entity_identifiers),
        published_at=None,
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
    )
    source = MoexBondsSource(clock=lambda: FETCHED_AT)
    parsed = source.parse(broken, raw)
    assert parsed
    assert all(item.quality_status == RecordQuality.QUARANTINE for item in parsed)
    assert all("content_hash_mismatch" in item.limitations for item in parsed)


def test_html_board_is_blocked_with_the_status_code() -> None:
    def handler(url: str, _params: dict[str, object]) -> httpx.Response:
        return _response(url, b"<html>subscriber</html>", content_type="text/html")

    http = _FakeHttp(handler)
    source = _source(http)
    report = source.discover()
    assert report.status == AdapterStatus.BLOCKED
    assert source.fetch_sample(limit=30) == ()
    assert source.inspect_coverage().status == AdapterStatus.BLOCKED
    text = " ".join(report.limitations)
    assert "TQOB:http_status=200" in text
    assert "TQCB:http_status=200" in text
    assert "html_body" in text
    assert all("/history/" not in url for url, _params in http.calls)
    assert source.secid is None


def test_empty_tqob_falls_through_to_tqcb() -> None:
    empty = json.dumps({"securities": {"columns": ["SECID"], "data": []}}).encode()
    tqcb = json.dumps(
        {
            "securities": {
                "columns": ["SECID", "ISIN", "LOTSIZE", "FACEUNIT"],
                "data": [["RUCB1", "RUCB1", 1, "SUR"]],
            }
        }
    ).encode()

    def handler(url: str, _params: dict[str, object]) -> httpx.Response:
        if "/boards/TQOB/" in url:
            return _response(url, empty)
        if "/boards/TQCB/" in url:
            return _response(url, tqcb)
        raise AssertionError(url)

    source = _source(_FakeHttp(handler))
    report = source.discover()
    assert report.status == AdapterStatus.READY
    assert source.boards_requested == ["TQOB", "TQCB"]
    assert source.board == "TQCB"
    assert source.secid == "RUCB1"
    assert "TQOB:http_status=200" in report.limitations
    assert "TQOB:empty_catalogue" in report.limitations
    parsed = source.parse(source.catalogue_artifact, source.raw_for(source.catalogue_artifact))  # type: ignore[arg-type]
    assert parsed[0].extra["face_currency"] == "RUB"
    assert parsed[0].extra["faceunit_raw"] == "SUR"


def test_empty_history_json_is_blocked_with_the_status_code() -> None:
    catalogue = json.dumps(
        {"securities": {"columns": ["SECID", "ISIN", "FACEUNIT"], "data": [["SU1", "SU1", "RUB"]]}}
    ).encode()
    history = json.dumps(
        {"history": {"columns": ["TRADEDATE", "LEGALCLOSEPRICE", "CLOSE"], "data": []}}
    ).encode()

    def handler(url: str, _params: dict[str, object]) -> httpx.Response:
        if "/history/" in url:
            return _response(url, history)
        return _response(url, catalogue)

    source = _source(_FakeHttp(handler))
    artifacts = source.fetch_sample(limit=30)
    coverage = source.inspect_coverage()
    assert len(artifacts) == 1
    assert artifacts[0].fetch_status == FetchStatus.EMPTY
    assert artifacts[0].historical_pit_quality == PitQuality.RESEARCH_ONLY
    assert artifacts[0].published_at is None
    assert artifacts[0].event_date is None
    assert "http_status=200" in artifacts[0].limitations
    assert "empty_history" in artifacts[0].limitations
    assert coverage.status == AdapterStatus.BLOCKED
    assert source.parse(artifacts[0], history) == ()


def test_history_html_and_http_error_are_blocked_with_the_status_code() -> None:
    catalogue = json.dumps(
        {"securities": {"columns": ["SECID"], "data": [["SU1"]]}}
    ).encode()

    def html_handler(url: str, _params: dict[str, object]) -> httpx.Response:
        if "/history/" in url:
            return _response(url, b"<html>denied</html>", content_type="text/html")
        return _response(url, catalogue)

    html_source = _source(_FakeHttp(html_handler))
    html_artifact = html_source.fetch_sample(limit=30)[0]
    assert html_artifact.fetch_status == FetchStatus.UNSUPPORTED
    assert "http_status=200" in html_artifact.limitations
    assert "html_body" in html_artifact.limitations
    assert html_source.inspect_coverage().status == AdapterStatus.BLOCKED
    assert html_artifact.historical_pit_quality != PitQuality.PIT_VERIFIED

    def error_handler(url: str, _params: dict[str, object]) -> httpx.Response:
        if "/history/" in url:
            return _response(url, b"busy", status=503, content_type="text/plain")
        return _response(url, catalogue)

    error_source = _source(_FakeHttp(error_handler))
    error_artifact = error_source.fetch_sample(limit=30)[0]
    assert error_artifact.fetch_status == FetchStatus.FAILED
    assert "http_status=503" in error_artifact.limitations
    assert error_source.inspect_coverage().status == AdapterStatus.BLOCKED


def test_cursor_total_does_not_page_or_invent_rows() -> None:
    catalogue = json.dumps(
        {"securities": {"columns": ["SECID"], "data": [["SU1"]]}}
    ).encode()
    history = json.dumps(
        {
            "history": {
                "columns": ["TRADEDATE", "LEGALCLOSEPRICE"],
                "data": [["2026-10-09", 99.1], ["2026-10-12", 99.2]],
            },
            "history.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[0, 500, 100]]},
        }
    ).encode()

    def handler(url: str, _params: dict[str, object]) -> httpx.Response:
        if "/history/" in url:
            return _response(url, history)
        return _response(url, catalogue)

    http = _FakeHttp(handler)
    source = _source(http)
    artifacts = source.fetch_sample(limit=30)
    observations = source.parse(artifacts[0], history)
    assert sum("/history/" in url for url, _params in http.calls) == 1
    assert len(observations) == 2
    assert source.history_cursor_total == 500
    assert "history_cursor_total_not_paged" in artifacts[0].limitations
