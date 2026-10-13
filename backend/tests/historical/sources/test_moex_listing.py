"""Offline MOEX-02 / MOEX-03 probe. HTTP is the saved ISS fixture, not the network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from app.infrastructure.market.http_client import MarketHttpClient
from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.moex_listing.source import (
    BOARD_CATALOGUE_URL,
    BOARDS_SOURCE_ID,
    LISTING_SOURCE_ID,
    LISTING_URL,
    ROW_CAP,
    SECURITY_BOARDS_URL,
    MoexListingSource,
)

FIXTURES = (
    Path(__file__).resolve().parents[3] / "app" / "modules" / "historical" / "sources" / "moex_listing" / "fixtures"
)
CLOCK = datetime(2026, 10, 13, 5, 28, tzinfo=UTC)


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _rows(name: str, block: str) -> list[dict[str, object]]:
    payload = json.loads(_load(name))
    columns = payload[block]["columns"]
    return [dict(zip(columns, row, strict=False)) for row in payload[block]["data"]]


def _description_value(name: str) -> str:
    for row in _rows("sber_description.json", "description"):
        if row["name"] == name:
            return str(row["value"])
    raise AssertionError(name)


def _install(monkeypatch: pytest.MonkeyPatch, listing: bytes | None = None) -> list[tuple[str, dict[str, object]]]:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_get(self: MarketHttpClient, url: str, **kwargs: object) -> httpx.Response:
        del self
        params = kwargs.get("params") or {}
        if not isinstance(params, dict):
            raise AssertionError(params)
        calls.append((url, params))
        if params.get("iss.only") == "description":
            raise AssertionError("description endpoint is not a listing source")
        if url == LISTING_URL:
            if params.get("start") not in (0, "0"):
                raise AssertionError(params)
            body = listing if listing is not None else _load("listing_shares_page1.json")
        elif url == BOARD_CATALOGUE_URL:
            body = _load("shares_boards.json")
        elif url == SECURITY_BOARDS_URL:
            if params.get("iss.only") != "boards":
                raise AssertionError(params)
            body = _load("sber_boards.json")
        else:
            raise AssertionError(url)
        return httpx.Response(200, content=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(MarketHttpClient, "get", fake_get)
    return calls


def _source() -> MoexListingSource:
    return MoexListingSource(clock=lambda: CLOCK)


def test_probe_note_matches_saved_fixtures() -> None:
    note = json.loads((FIXTURES / "probe_note.json").read_text(encoding="utf-8"))
    assert note["moex_02_status"] == "BLOCKED"
    assert note["moex_02_pit"] == "RESEARCH_ONLY"
    assert note["moex_03_status"] == "PARTIAL"
    assert note["moex_03_pit"] == "RESEARCH_ONLY"
    assert note["listing_history_list_delist_fields_present"] is False
    assert note["description_treated_as_listing_event"] is False
    assert note["period_end_used_as_first_observed_at"] is False
    assert note["row_cap"] == ROW_CAP
    by_fixture = {item["fixture"]: item for item in note["endpoints"] if "fixture" in item}
    assert by_fixture["listing_shares_page1.json"]["rows"] == len(_rows("listing_shares_page1.json", "securities"))
    assert by_fixture["listing_shares_page1.json"]["columns"] == [
        "SECID",
        "SHORTNAME",
        "NAME",
        "BOARDID",
        "decimals",
        "history_from",
        "history_till",
    ]
    assert "listed_from" in by_fixture["listing_shares_page1.json"]["absent_columns"]
    assert "listed_till" in by_fixture["listing_shares_page1.json"]["absent_columns"]
    assert by_fixture["shares_boards.json"]["rows"] == len(_rows("shares_boards.json", "boards"))
    assert by_fixture["sber_boards.json"]["rows"] == len(_rows("sber_boards.json", "boards"))
    assert by_fixture["sber_description.json"]["rows"] == len(_rows("sber_description.json", "description"))
    assert by_fixture["sber_description.json"]["treated_as_listing_event"] is False
    assert "ISSUEDATE" in by_fixture["sber_description.json"]["description_names"]
    assert "listed_from" not in by_fixture["sber_description.json"]["description_names"]
    statuses = {item["url"]: item["http_status"] for item in note["endpoints"]}
    listing_url = "https://iss.moex.com/iss/history/engines/stock/markets/shares/listing.json?iss.meta=off&start=0"
    assert statuses[listing_url] == 200
    assert statuses["https://iss.moex.com/iss/engines/stock/markets/shares/boards.json?iss.meta=off"] == 200
    assert statuses["https://iss.moex.com/iss/securities/SBER.json?iss.meta=off&iss.only=boards"] == 200
    assert statuses["https://iss.moex.com/iss/securities/SBER.json?iss.meta=off&iss.only=description"] == 200
    assert statuses["https://iss.moex.com/iss/history/engines/stock/markets/shares.json?iss.meta=off"] == 404


def test_offline_probe_emits_secid_board_and_only_real_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install(monkeypatch)
    source = _source()
    listing, catalogue, boards = source.fetch_sample(limit=100)
    assert [url for url, _params in calls] == [LISTING_URL, BOARD_CATALOGUE_URL, SECURITY_BOARDS_URL]
    assert calls[0][1]["start"] == "0"
    assert "limit" not in calls[0][1]
    assert calls[2][1]["iss.only"] == "boards"
    assert all("cci" not in url for url, _params in calls)

    assert listing.source_id == LISTING_SOURCE_ID
    assert listing.fetch_status == FetchStatus.OK
    assert listing.quality_status == RecordQuality.UNRESOLVED
    assert listing.historical_pit_quality == PitQuality.RESEARCH_ONLY
    assert listing.historical_pit_quality != PitQuality.PIT_VERIFIED
    assert listing.published_at is None
    assert listing.published_at_precision == PublishedAtPrecision.UNKNOWN
    assert listing.period_end is None
    assert listing.event_date is None
    assert listing.first_observed_at == CLOCK
    assert listing.chronology_errors() == ()
    assert "no_listed_from_column" in listing.limitations
    assert "history_window_is_not_a_listing_event" in listing.limitations

    listing_rows = source.parse(listing, _load("listing_shares_page1.json"))
    assert len(listing_rows) == 100
    first = listing_rows[0]
    assert first.issuer_identity == {"secid": "ABBN", "board": "SMAL"}
    assert first.extra["history_from"] == "2017-12-15"
    assert first.extra["history_till"] == "2018-04-25"
    assert first.extra["listed_from"] is None
    assert first.extra["listed_till"] is None
    assert first.period_end is None
    assert first.quality_status == RecordQuality.UNRESOLVED
    assert "no_list_delist_field" in first.limitations
    assert all(row.period_end is None for row in listing_rows)
    assert all(row.extra["listed_from"] is None and row.extra["listed_till"] is None for row in listing_rows)

    assert catalogue.source_id == BOARDS_SOURCE_ID
    assert catalogue.first_observed_at == CLOCK
    assert catalogue.period_end is None
    catalogue_rows = source.parse(catalogue, _load("shares_boards.json"))
    assert len(catalogue_rows) == 35
    assert catalogue_rows[0].issuer_identity == {"board": "EQBR"}
    assert "secid" not in catalogue_rows[0].issuer_identity
    assert catalogue_rows[0].extra["listed_from"] is None
    assert catalogue_rows[0].extra["listed_till"] is None
    assert catalogue_rows[0].period_end is None

    assert boards.entity_identifiers["secid"] == "SBER"
    assert boards.first_observed_at == CLOCK
    assert boards.period_end is None
    assert boards.historical_pit_quality == PitQuality.RESEARCH_ONLY
    assert boards.published_at is None
    windows = source.parse(boards, _load("sber_boards.json"))
    assert len(windows) == 51
    tqbr = next(row for row in windows if row.issuer_identity["board"] == "TQBR")
    assert tqbr.issuer_identity["secid"] == "SBER"
    assert tqbr.extra["listed_from"] == "2013-03-25"
    assert tqbr.extra["listed_till"] == "2026-10-13"
    assert tqbr.extra["history_from"] == "2013-03-25"
    assert tqbr.extra["history_till"] == "2026-10-12"
    assert tqbr.period_end is None
    assert tqbr.quality_status == RecordQuality.ACCEPTED
    assert "listed_till_is_not_a_delist_event" in tqbr.limitations
    assert boards.first_observed_at != datetime(2026, 10, 13, tzinfo=UTC)
    eqbr = next(row for row in windows if row.issuer_identity["board"] == "EQBR")
    assert eqbr.extra["listed_from"] == "2011-11-21"
    assert eqbr.extra["listed_till"] == "2013-08-30"
    assert eqbr.extra["history_till"] == "2013-08-30"
    assert sum(row.extra["history_from"] is None for row in windows) == 16
    assert all(row.extra["listed_from"] for row in windows)

    checked = source.validate(listing_rows + catalogue_rows + windows)
    assert checked[0].quality_status == RecordQuality.UNRESOLVED
    assert all(row.quality_status == RecordQuality.ACCEPTED for row in checked[100:])

    assert source.discover().status == AdapterStatus.BLOCKED
    assert source.discover().earliest is None
    assert source.discover().latest is None
    coverage = source.inspect_coverage()
    assert coverage.source_id == BOARDS_SOURCE_ID
    assert coverage.status == AdapterStatus.PARTIAL
    assert coverage.earliest is None
    assert coverage.latest is None


def test_description_payload_is_not_a_listing_event(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    source = _source()
    listing, _catalogue, boards = source.fetch_sample(limit=100)
    description = _load("sber_description.json")
    assert source.parse(listing, description) == ()
    assert source.parse(boards, description) == ()
    issued = _description_value("ISSUEDATE")
    decision = _description_value("DECISIONDATE")
    registry = _description_value("REGISTRY_DATE")
    merged = json.loads(_load("sber_boards.json"))
    merged["description"] = json.loads(description)["description"]
    parsed = source.parse(boards, json.dumps(merged).encode("utf-8"))
    assert len(parsed) == 51
    assert all(row.quality_status == RecordQuality.QUARANTINE for row in parsed)
    blob = json.dumps([row.extra for row in parsed])
    assert issued not in blob
    assert decision not in blob
    assert registry not in blob
    assert all(row.period_end is None for row in parsed)
    assert all(row.metric_id == "market.board.window" for row in parsed)


def test_listing_page_is_capped_at_100_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    columns = ["SECID", "SHORTNAME", "NAME", "BOARDID", "decimals", "history_from", "history_till"]
    data = [[f"S{index:03d}", "name", "full", "TQBR", 2, "2010-01-04", "2011-02-01"] for index in range(150)]
    body = json.dumps({"securities": {"columns": columns, "data": data}}).encode("utf-8")
    _install(monkeypatch, listing=body)
    source = _source()
    listing, _catalogue, _boards = source.fetch_sample(limit=1000)
    assert "truncated_to_100" in listing.limitations
    assert "response_rows=150" in listing.limitations
    assert "kept_rows=100" in listing.limitations
    parsed = source.parse(listing, body)
    assert len(parsed) == ROW_CAP
    assert parsed[-1].issuer_identity["secid"] == "S099"
    assert all(row.issuer_identity["secid"] != "S100" for row in parsed)


def test_date_window_does_not_become_first_observed_at(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install(monkeypatch)
    source = _source()
    assert source.fetch_range(start=date(2011, 11, 21), end=date(2026, 10, 13), limit=100) == ()
    assert calls == []
    listing, _catalogue, boards = source.fetch_sample(limit=100)
    assert source.fetch_range(start=date(2013, 3, 25), end=CLOCK.date(), limit=30) == ()
    assert listing.first_observed_at == CLOCK
    assert boards.first_observed_at == CLOCK
    assert boards.period_end is None
    assert listing.period_end is None
