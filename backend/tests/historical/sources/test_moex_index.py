"""Offline MOEX-05 IMOEX sample. HTTP is the saved live fixture, not the network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
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
from app.modules.historical.sources.moex_index import source as moex_index
from app.modules.historical.sources.moex_index.source import (
    ISS_INDEX_PIT_EVIDENCE,
    MAX_SESSIONS,
    PILOT_FROM,
    PILOT_TILL,
    SECID,
    SOURCE_ID,
    MoexIndexSource,
    assert_single_window,
    bounded_weekday_window,
    index_history_url,
)

PACKAGE = Path(__file__).resolve().parents[3] / "app" / "modules" / "historical" / "sources" / "moex_index"
FIXTURES = PACKAGE / "fixtures"
FIXTURE_NAME = "imoex_sndx_window.json"
FETCHED_AT = datetime(2026, 10, 13, 5, 28, tzinfo=UTC)
HISTORY_URL = "https://iss.moex.com/iss/history/engines/stock/markets/index/boards/SNDX/securities/IMOEX.json"
FORBIDDEN = (
    "prospective_captures",
    "signal_outputs",
    "committee_decisions",
    "shadow.orders",
    "broker.executions",
    "polza",
)


def _load(name: str = FIXTURE_NAME) -> bytes:
    return (FIXTURES / name).read_bytes()


def _history_rows(raw: bytes | None = None) -> list[dict[str, object]]:
    payload = json.loads(raw if raw is not None else _load())
    columns = payload["history"]["columns"]
    return [dict(zip(columns, row, strict=False)) for row in payload["history"]["data"]]


def _install_http(monkeypatch: pytest.MonkeyPatch, body: bytes | None = None) -> list[tuple[str, dict[str, object]]]:
    calls: list[tuple[str, dict[str, object]]] = []
    payload = body if body is not None else _load()

    def fake_get(self: MarketHttpClient, url: str, **kwargs: object) -> httpx.Response:
        params = kwargs.get("params") or {}
        if not isinstance(params, dict):
            raise AssertionError(params)
        calls.append((url, params))
        if params.get("start") not in (0, "0"):
            raise AssertionError(params)
        if "/iss/history/" not in url:
            raise AssertionError(url)
        return httpx.Response(200, content=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(MarketHttpClient, "get", fake_get)
    return calls


def _source() -> MoexIndexSource:
    return MoexIndexSource(clock=lambda: FETCHED_AT, base_url="https://iss.moex.com")


def _weekday_count(start: date, end: date) -> int:
    count = 0
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            count += 1
        cursor = date.fromordinal(cursor.toordinal() + 1)
    return count


def test_weekday_window_never_exceeds_one_hundred_sessions() -> None:
    window = bounded_weekday_window(date(2000, 1, 1), date(2026, 10, 13), limit=500)
    assert window is not None
    start, end = window
    assert end == date(2026, 10, 13)
    assert _weekday_count(start, end) == MAX_SESSIONS
    pilot = bounded_weekday_window(PILOT_FROM, PILOT_TILL, limit=MAX_SESSIONS)
    assert pilot == (PILOT_FROM, PILOT_TILL)
    assert _weekday_count(PILOT_FROM, PILOT_TILL) <= MAX_SESSIONS


def test_package_does_not_name_forbidden_write_targets_or_paginate() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE.glob("*.py"))
    lowered = text.lower()
    for token in FORBIDDEN:
        assert token not in lowered
    assert "httpx.Client(" not in text
    assert "while True" not in text
    assert "start +=" not in text


def test_live_probe_matches_the_saved_window() -> None:
    note = json.loads((PACKAGE / "live_probe.json").read_text(encoding="utf-8"))
    raw = _load()
    rows = _history_rows(raw)
    payload = json.loads(raw)
    cursor = payload["history.cursor"]["data"][0]
    trade_dates = [str(row["TRADEDATE"]) for row in rows]
    assert note["live_probe"] is True
    assert note["http_status"] == 200
    assert note["url"].startswith(HISTORY_URL)
    assert note["pages_requested"] == 1
    assert note["start"] == 0
    assert note["session_count"] == len(rows) == cursor[1]
    assert 1 <= note["session_count"] <= MAX_SESSIONS
    assert note["cursor_pagesize"] == 100
    assert note["first_trade_date"] == trade_dates[0] == "2026-09-01"
    assert note["last_trade_date"] == trade_dates[-1] == "2026-10-12"
    assert note["publication_timestamp_columns"] == []
    assert note["recalc_date_non_null"] == 0
    assert note["trade_session_date_matches_trade_date"] is True
    assert note["close_missing"] == 0
    assert note["duplicate_trade_dates"] is False
    assert note["pit_quality"] == "PIT_PROXY"
    assert note["bytes"] == len(raw)
    assert {row["SECID"] for row in rows} == {SECID}


def test_pilot_window_keeps_trade_date_as_period_end(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_http(monkeypatch)
    source = _source()

    pending = source.inspect_coverage()
    artifacts = source.fetch_range(start=PILOT_FROM, end=PILOT_TILL, limit=MAX_SESSIONS)
    again = source.fetch_range(start=PILOT_FROM, end=PILOT_TILL, limit=MAX_SESSIONS)
    coverage = source.inspect_coverage()

    assert pending.status.value == "PENDING"
    assert again is artifacts
    assert len(calls) == 1
    url, params = calls[0]
    assert url == index_history_url("https://iss.moex.com") == HISTORY_URL
    assert params == {
        "from": "2026-09-01",
        "till": "2026-10-13",
        "start": 0,
        "iss.meta": "off",
    }
    assert "history.columns" not in params
    assert source.last_http_status == 200

    artifact = artifacts[0]
    rows = _history_rows()
    observations = source.validate(source.parse(artifact, source.raw_for(artifact)))
    assert artifact.source_id == SOURCE_ID
    assert artifact.document_type == "index_history"
    assert artifact.fetch_status == FetchStatus.OK
    assert artifact.first_observed_at == FETCHED_AT
    assert artifact.published_at is None
    assert artifact.published_at_precision == PublishedAtPrecision.PERIOD_ONLY
    assert artifact.historical_pit_quality == PitQuality.PIT_PROXY
    assert artifact.historical_availability_evidence == ISS_INDEX_PIT_EVIDENCE
    assert artifact.chronology_errors() == ()
    assert artifact.period_end == date(2026, 10, 12)
    assert artifact.event_date == artifact.period_end
    assert artifact.period_end != PILOT_TILL
    assert artifact.period_end != FETCHED_AT.date()
    assert artifact.entity_identifiers == {"secid": "IMOEX", "board": "SNDX"}
    assert "id" not in artifact.entity_identifiers
    assert coverage.status.value == "READY"
    assert coverage.earliest == date(2026, 9, 1)
    assert coverage.latest == date(2026, 10, 12)
    assert len(observations) == len(rows) == source.session_count <= MAX_SESSIONS
    for row, obs in zip(rows, observations, strict=True):
        trade_date = str(row["TRADEDATE"])
        assert obs.period == trade_date
        assert obs.period_end == date.fromisoformat(trade_date)
        assert obs.metric_id == "market.index.close"
        assert obs.quality_status == RecordQuality.ACCEPTED
        assert obs.quality_errors() == ()
        assert obs.extra["trade_date"] == trade_date
        assert "known_at" not in obs.extra
        assert "published_at" not in obs.extra
        close = Decimal(str(row["CLOSE"]))
        assert obs.extra["close"] == format(close, "f")
        assert obs.value == float(close)


def test_discover_uses_the_same_single_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_http(monkeypatch)
    source = _source()

    first = source.discover()
    second = source.discover()

    assert second.earliest == first.earliest
    assert second.latest == first.latest
    assert len(calls) == 1
    assert first.earliest == date(2026, 9, 1)
    assert first.latest == date(2026, 10, 12)
    assert first.status.value == "READY"


def test_missing_close_is_skipped() -> None:
    raw = json.dumps(
        {
            "history": {
                "columns": ["TRADEDATE", "CLOSE"],
                "data": [["2026-10-01", None], ["2026-10-02", "10.5"]],
            }
        }
    ).encode()
    holder = HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=HISTORY_URL,
        external_document_id="SNDX:IMOEX:skip",
        document_type="index_history",
        content_hash=moex_index._sha256(raw),
        parser_version="moex_index_history_v1",
        fetch_status=FetchStatus.OK,
        first_observed_at=FETCHED_AT,
        published_at=None,
        published_at_precision=PublishedAtPrecision.PERIOD_ONLY,
        historical_pit_quality=PitQuality.PIT_PROXY,
        historical_availability_evidence=ISS_INDEX_PIT_EVIDENCE,
    )
    parsed = MoexIndexSource(clock=lambda: FETCHED_AT).parse(holder, raw)
    assert len(parsed) == 1
    assert parsed[0].period_end == date(2026, 10, 2)
    assert parsed[0].extra["close"] == "10.5"


def test_zero_close_must_be_marked_explicit() -> None:
    raw = json.dumps({"history": {"columns": ["TRADEDATE", "CLOSE"], "data": [["2026-10-09", 0]]}}).encode()
    artifact = HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=HISTORY_URL,
        external_document_id="SNDX:IMOEX:zero",
        document_type="index_history",
        content_hash=moex_index._sha256(raw),
        parser_version="moex_index_history_v1",
        fetch_status=FetchStatus.OK,
        first_observed_at=FETCHED_AT,
        entity_identifiers={"secid": "IMOEX", "board": "SNDX"},
        period_end=date(2026, 10, 9),
        event_date=date(2026, 10, 9),
        published_at=None,
        published_at_precision=PublishedAtPrecision.PERIOD_ONLY,
        historical_availability_evidence=ISS_INDEX_PIT_EVIDENCE,
        historical_pit_quality=PitQuality.PIT_PROXY,
    )
    source = MoexIndexSource(clock=lambda: FETCHED_AT)
    parsed = source.parse(artifact, raw)
    assert parsed[0].limitations == ("explicit_zero",)
    assert source.validate(parsed)[0].quality_status == RecordQuality.ACCEPTED


def test_hash_mismatch_quarantines_observations() -> None:
    raw = _load()
    artifact = HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=HISTORY_URL,
        external_document_id="SNDX:IMOEX:mismatch",
        document_type="index_history",
        content_hash="0" * 64,
        parser_version="moex_index_history_v1",
        fetch_status=FetchStatus.OK,
        first_observed_at=FETCHED_AT,
        published_at=None,
        published_at_precision=PublishedAtPrecision.PERIOD_ONLY,
        historical_pit_quality=PitQuality.PIT_PROXY,
        historical_availability_evidence=ISS_INDEX_PIT_EVIDENCE,
    )
    parsed = MoexIndexSource(clock=lambda: FETCHED_AT).parse(artifact, raw)
    assert parsed
    assert all(item.quality_status == RecordQuality.QUARANTINE for item in parsed)
    assert all("content_hash_mismatch" in item.limitations for item in parsed)


def test_refuses_a_window_that_would_need_another_page(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(
        {
            "history": {"columns": ["TRADEDATE", "CLOSE"], "data": [["2026-10-12", "1"]]},
            "history.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[0, 40, 100]]},
        }
    ).encode()
    calls = _install_http(monkeypatch, body)
    source = _source()

    with pytest.raises(RuntimeError, match="refusing to paginate"):
        source.fetch_sample()

    assert len(calls) == 1
    assert calls[0][1]["start"] == 0


def test_cap_rejects_more_than_one_hundred_sessions() -> None:
    payload = {
        "history": {"columns": ["TRADEDATE", "CLOSE"], "data": [["2026-10-12", "1"]]},
        "history.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[0, 101, 100]]},
    }
    with pytest.raises(RuntimeError, match="cap is 100"):
        assert_single_window(payload, 1)


def test_publication_timestamp_on_another_day_is_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(
        {
            "history": {
                "columns": ["TRADEDATE", "CLOSE", "PUBLISHED_AT"],
                "data": [["2026-10-09", "2000.5", "2026-10-10 12:00:00"]],
            },
            "history.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[0, 1, 100]]},
        }
    ).encode()
    _install_http(monkeypatch, body)
    artifact = _source().fetch_sample()[0]

    assert artifact.published_at == datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    assert artifact.published_at_precision == PublishedAtPrecision.TIMESTAMP
    assert artifact.historical_pit_quality == PitQuality.PIT_VERIFIED
    assert artifact.period_end == date(2026, 10, 9)
    assert artifact.published_at.date() != artifact.period_end
    assert artifact.chronology_errors() == ()


def test_same_day_timestamp_is_not_stored_as_published_at(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(
        {
            "history": {
                "columns": ["TRADEDATE", "CLOSE", "RECALC_DATE", "PUBLISHED_AT"],
                "data": [["2026-10-12", "2389.04", "2026-10-12", "2026-10-12 19:00:00"]],
            },
            "history.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[0, 1, 100]]},
        }
    ).encode()
    _install_http(monkeypatch, body)
    artifact = _source().fetch_sample()[0]

    assert artifact.period_end == date(2026, 10, 12)
    assert artifact.published_at is None
    assert artifact.historical_pit_quality == PitQuality.PIT_PROXY
    assert "publication_timestamp_collides_with_period_end" in artifact.limitations
    assert artifact.chronology_errors() == ()
