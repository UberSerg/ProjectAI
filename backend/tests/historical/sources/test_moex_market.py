"""Offline MOEX-01 / MOEX-04 sample. HTTP is the saved live fixture, not the network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from app.infrastructure.market.http_client import MarketHttpClient
from app.modules.historical.domain.evidence import (
    FetchStatus,
    HistoricalArtifact,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.moex_market import source as moex_source
from app.modules.historical.sources.moex_market.source import (
    CANDLE_SOURCE_ID,
    CATALOGUE_SOURCE_ID,
    ISS_HISTORY_PIT_EVIDENCE,
    MAX_TRADING_DAYS,
    PILOT_SYMBOLS,
    MoexMarketSource,
    bounded_weekday_window,
)
from app.modules.market.application.instrument_search import resolve_instrument_ref

PACKAGE = Path(__file__).resolve().parents[3] / "app" / "modules" / "historical" / "sources" / "moex_market"
FIXTURES = PACKAGE / "fixtures"
FETCHED_AT = datetime(2026, 10, 12, 20, 29, tzinfo=UTC)
FORBIDDEN = (
    "prospective_captures",
    "signal_outputs",
    "committee_decisions",
    "shadow.orders",
    "broker.executions",
    "polza",
)


class _Instrument:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.primary_board = "TQBR"
        self.isin = f"TEST-{symbol}"
        self.name = symbol
        self._database_id = 900000 + len(symbol)

    @property
    def id(self) -> int:
        raise AssertionError("database id must not be read")


class _MasterSession:
    """Stand-in session. Resolution is patched, so this object is never queried."""


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _history_rows(name: str) -> list[dict[str, object]]:
    payload = json.loads(_load(name))
    columns = payload["history"]["columns"]
    return [dict(zip(columns, row, strict=False)) for row in payload["history"]["data"]]


def _install_http(
    monkeypatch: pytest.MonkeyPatch, boards: dict[str, bytes] | None = None
) -> list[tuple[str, dict[str, object]]]:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_get(self: MarketHttpClient, url: str, **kwargs: object) -> httpx.Response:
        params = kwargs.get("params") or {}
        if not isinstance(params, dict):
            raise AssertionError(params)
        calls.append((url, params))
        if url.endswith("/boards/TQBR/securities.json"):
            if params.get("securities.start") not in (0, "0"):
                raise AssertionError(params)
            body = _load("tqbr_securities_page1.json")
        elif "/iss/history/" in url:
            if params.get("start") not in (0, "0"):
                raise AssertionError(params)
            secid = url.rsplit("/", 1)[-1].removesuffix(".json")
            body = _load(f"eod_{secid}.json")
        elif boards is not None and "/iss/securities/" in url:
            secid = url.rsplit("/", 1)[-1].removesuffix(".json")
            body = boards[secid]
        else:
            raise AssertionError(url)
        return httpx.Response(200, content=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(MarketHttpClient, "get", fake_get)
    return calls


def _patch_master(monkeypatch: pytest.MonkeyPatch) -> _MasterSession:
    session = _MasterSession()
    instruments = {symbol: _Instrument(symbol) for symbol in PILOT_SYMBOLS}

    def fake_resolve(bound: object, ref: str) -> _Instrument | None:
        assert bound is session
        return instruments.get(ref.strip().upper())

    monkeypatch.setattr(moex_source, "resolve_instrument_ref", fake_resolve)
    return session


def _source(session: object) -> MoexMarketSource:
    return MoexMarketSource(session=session, clock=lambda: FETCHED_AT)  # type: ignore[arg-type]


def test_weekday_window_caps_the_pilot_at_thirty_sessions() -> None:
    window = bounded_weekday_window(date(2020, 1, 1), date(2026, 10, 12), limit=100)
    assert window == (date(2026, 9, 1), date(2026, 10, 12))
    start, end = window
    weekdays = 0
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            weekdays += 1
        cursor = date.fromordinal(cursor.toordinal() + 1)
    assert weekdays == MAX_TRADING_DAYS


def test_package_does_not_name_forbidden_write_targets() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE.glob("*.py"))
    lowered = text.lower()
    for token in FORBIDDEN:
        assert token not in lowered
    assert "httpx.Client(" not in text


def test_live_probe_note_matches_saved_fixtures() -> None:
    note = json.loads((PACKAGE / "live_probe.json").read_text(encoding="utf-8"))
    assert set(note) == {
        "candle_requests",
        "candle_rows",
        "catalogue_pages",
        "catalogue_response_rows",
        "catalogue_rows",
        "live_probe",
        "resolved_via",
        "securities",
    }
    assert note["live_probe"] is True
    assert note["catalogue_pages"] == 1
    assert note["securities"] == 3
    assert note["candle_requests"] == 3
    catalogue = json.loads(_load("tqbr_securities_page1.json"))
    assert note["catalogue_rows"] == len(catalogue["securities"]["data"]) == 100
    assert note["catalogue_response_rows"] == 512
    assert set(note["candle_rows"]) == set(PILOT_SYMBOLS)
    for symbol, count in note["candle_rows"].items():
        rows = _history_rows(f"eod_{symbol}.json")
        assert count == len(rows)
        assert 1 <= count <= MAX_TRADING_DAYS


def test_discover_reads_only_the_first_tqbr_page(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_http(monkeypatch)
    session = _patch_master(monkeypatch)
    source = _source(session)

    first = source.discover()
    second = source.discover()
    artifact = source.catalogue_artifact
    assert artifact is not None
    observations = source.validate(source.parse(artifact, source.raw_for(artifact)))

    assert first.status.value == "READY"
    assert second is first
    assert [url for url, _params in calls] == [
        "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
    ]
    assert calls[0][1]["securities.start"] == 0
    assert calls[0][1]["limit"] == 100
    assert artifact.source_id == CATALOGUE_SOURCE_ID
    assert artifact.first_observed_at == FETCHED_AT
    assert artifact.published_at is None
    assert artifact.historical_pit_quality == PitQuality.RESEARCH_ONLY
    assert artifact.fetch_status == FetchStatus.OK
    assert artifact.chronology_errors() == ()
    assert len(observations) == 100
    assert observations[0].quality_status == RecordQuality.ACCEPTED
    assert observations[0].metric_id == "market.catalogue.security"
    assert "id" not in artifact.entity_identifiers


def test_catalogue_parse_keeps_only_the_first_hundred_rows() -> None:
    payload = json.loads(_load("tqbr_securities_page1.json"))
    data = payload["securities"]["data"]
    payload["securities"]["data"] = data + data[:1]
    raw = json.dumps(payload).encode()
    artifact = HistoricalArtifact(
        source_id=CATALOGUE_SOURCE_ID,
        source_url="https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json",
        external_document_id="TQBR:page1",
        document_type="instrument_catalogue",
        content_hash=moex_source._sha256(raw),
        parser_version="moex_market_catalogue_v1",
        fetch_status=FetchStatus.OK,
        first_observed_at=FETCHED_AT,
        published_at=None,
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
    )
    source = MoexMarketSource(session=None, clock=lambda: FETCHED_AT, symbols=("SBER",))
    observations = source.parse(artifact, raw)
    assert len(data) == 100
    assert len(observations) == 100
    assert observations[0].issuer_identity["secid"] == data[0][0]
    assert observations[-1].issuer_identity["secid"] == data[-1][0]


def test_eod_sample_uses_trade_date_as_period_not_known_at(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_http(monkeypatch)
    session = _patch_master(monkeypatch)
    source = _source(session)

    artifacts = source.fetch_range(start=date(2020, 1, 1), end=date(2026, 10, 12), limit=100)
    coverage = source.inspect_coverage()

    assert [item.entity_identifiers["secid"] for item in artifacts] == list(PILOT_SYMBOLS)
    assert coverage.earliest == date(2026, 9, 1)
    assert coverage.latest == date(2026, 10, 9)
    history_calls = [(url, params) for url, params in calls if "/iss/history/" in url]
    assert len(history_calls) == 3
    for url, params in history_calls:
        assert params["from"] == "2026-09-01"
        assert params["till"] == "2026-10-12"
        assert params["start"] == 0
        assert url.startswith("https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/")

    for artifact in artifacts:
        secid = artifact.entity_identifiers["secid"]
        assert artifact.source_id == CANDLE_SOURCE_ID
        assert artifact.document_type == "eod_candle_series"
        assert artifact.first_observed_at == FETCHED_AT
        assert artifact.published_at is None
        assert artifact.published_at_precision == PublishedAtPrecision.PERIOD_ONLY
        assert artifact.historical_pit_quality == PitQuality.PIT_PROXY
        assert artifact.historical_availability_evidence == ISS_HISTORY_PIT_EVIDENCE
        assert artifact.chronology_errors() == ()
        assert artifact.entity_identifiers["resolved_via"] == "instrument_master"
        assert artifact.entity_identifiers["isin"] == f"TEST-{secid}"
        assert "id" not in artifact.entity_identifiers
        assert "instrument_id" not in artifact.entity_identifiers
        rows = _history_rows(f"eod_{secid}.json")
        observations = source.validate(source.parse(artifact, _load(f"eod_{secid}.json")))
        assert len(observations) == len(rows) <= MAX_TRADING_DAYS
        assert artifact.event_date == date.fromisoformat(str(rows[-1]["TRADEDATE"]))
        assert artifact.period_end == artifact.event_date
        assert artifact.event_date != FETCHED_AT.date()
        for row, obs in zip(rows, observations, strict=True):
            trade_date = str(row["TRADEDATE"])
            assert obs.period == trade_date
            assert obs.period_end == date.fromisoformat(trade_date)
            assert obs.quality_status == RecordQuality.ACCEPTED
            assert obs.quality_errors() == ()
            assert "known_at" not in obs.extra
            assert obs.extra["trade_date"] == trade_date
            legal_close = row["LEGALCLOSEPRICE"]
            assert legal_close not in (None, "")
            assert obs.value == float(legal_close)  # type: ignore[arg-type]
            assert obs.extra["close"] == str(legal_close)


def test_iss_fallback_resolves_tqbr_without_a_database_id(monkeypatch: pytest.MonkeyPatch) -> None:
    boards = {
        "SBER": json.dumps(
            {
                "boards": {
                    "columns": ["secid", "boardid", "market", "is_primary", "is_traded"],
                    "data": [["SBER", "TQBR", "shares", 1, 1]],
                }
            }
        ).encode()
    }
    calls = _install_http(monkeypatch, boards=boards)
    source = MoexMarketSource(session=None, clock=lambda: FETCHED_AT, symbols=("SBER",))

    artifacts = source.fetch_sample(limit=30)

    assert source.resolve_securities()[0].resolved_via == "iss"
    assert artifacts[0].entity_identifiers["secid"] == "SBER"
    assert "id" not in artifacts[0].entity_identifiers
    assert any("/iss/securities/SBER.json" in url for url, _params in calls)
    assert sum("/iss/history/" in url for url, _params in calls) == 1


def test_zero_close_must_be_marked_explicit() -> None:
    raw = json.dumps(
        {
            "history": {
                "columns": ["TRADEDATE", "OPEN", "HIGH", "LOW", "CLOSE", "LEGALCLOSEPRICE", "VOLUME"],
                "data": [["2026-10-09", 0, 0, 0, 0, 0, 0]],
            }
        }
    ).encode()
    artifact = HistoricalArtifact(
        source_id=CANDLE_SOURCE_ID,
        source_url="https://iss.moex.com/iss/history/example.json",
        external_document_id="TQBR:TEST:zero",
        document_type="eod_candle_series",
        content_hash=moex_source._sha256(raw),
        parser_version="moex_market_eod_v1",
        fetch_status=FetchStatus.OK,
        first_observed_at=FETCHED_AT,
        entity_identifiers={"secid": "TEST", "board": "TQBR"},
        period_end=date(2026, 10, 9),
        event_date=date(2026, 10, 9),
        published_at=None,
        published_at_precision=PublishedAtPrecision.PERIOD_ONLY,
        historical_availability_evidence=ISS_HISTORY_PIT_EVIDENCE,
        historical_pit_quality=PitQuality.PIT_PROXY,
    )
    source = MoexMarketSource(session=None, clock=lambda: FETCHED_AT, symbols=("SBER",))
    parsed = source.parse(artifact, raw)
    assert parsed[0].limitations == ("explicit_zero",)
    assert source.validate(parsed)[0].quality_status == RecordQuality.ACCEPTED


def test_hash_mismatch_quarantines_observations() -> None:
    raw = _load("eod_SBER.json")
    artifact = HistoricalArtifact(
        source_id=CANDLE_SOURCE_ID,
        source_url="https://iss.moex.com/iss/history/example.json",
        external_document_id="TQBR:SBER:mismatch",
        document_type="eod_candle_series",
        content_hash="0" * 64,
        parser_version="moex_market_eod_v1",
        fetch_status=FetchStatus.OK,
        first_observed_at=FETCHED_AT,
        entity_identifiers={"secid": "SBER", "board": "TQBR"},
        published_at=None,
        published_at_precision=PublishedAtPrecision.PERIOD_ONLY,
        historical_pit_quality=PitQuality.PIT_PROXY,
        historical_availability_evidence=ISS_HISTORY_PIT_EVIDENCE,
    )
    source = MoexMarketSource(session=None, clock=lambda: FETCHED_AT, symbols=("SBER",))
    parsed = source.parse(artifact, raw)
    assert parsed
    assert all(item.quality_status == RecordQuality.QUARANTINE for item in parsed)
    assert all("content_hash_mismatch" in item.limitations for item in parsed)


def test_instrument_master_rows_resolve_sber_lkoh_mgnt(core_db: object) -> None:
    resolved = []
    for symbol in PILOT_SYMBOLS:
        instrument = resolve_instrument_ref(core_db, symbol)  # type: ignore[arg-type]
        assert instrument is not None
        assert instrument.symbol == symbol
        assert instrument.exchange == "MOEX"
        assert instrument.primary_board == "TQBR"
        resolved.append(instrument)
    assert len({row.id for row in resolved}) == 3
