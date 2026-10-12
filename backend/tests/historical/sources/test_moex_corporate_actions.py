"""Offline tests for the MOEX-06 dividend / corporate-action sample.

Live probe counts live in probe_note.json. These tests do not call ISS.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.moex_corporate_actions.source import (
    SAMPLE_CAP,
    FetchResponse,
    MoexCorporateActionsSource,
    fixture_bytes,
)

CLOCK = datetime(2026, 10, 12, 20, 23, tzinfo=UTC)
FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "modules"
    / "historical"
    / "sources"
    / "moex_corporate_actions"
    / "fixtures"
)
SOURCE_PATH = FIXTURES.parent / "source.py"


class MapTransport:
    def __init__(
        self,
        *,
        cci: dict[str, bytes],
        securities: dict[str, bytes] | None = None,
        bondization: dict[str, bytes] | None = None,
    ) -> None:
        self.cci = cci
        self.securities = securities or {}
        self.bondization = bondization or {}
        self.calls: list[str] = []

    def get(self, url: str, params: dict[str, str]) -> FetchResponse:
        self.calls.append(url)
        if url.endswith("/cci/corp-actions/dividends.json"):
            body = self.cci[params["security"]]
            content_type = "text/html" if body.lstrip().startswith(b"<") else "application/json"
            return FetchResponse(200, content_type, body)
        security = url.split("/securities/", 1)[1].split("/", 1)[0]
        if url.endswith("/bondization.json"):
            return FetchResponse(200, "application/json", self.bondization[security])
        if url.endswith("/dividends.json"):
            return FetchResponse(200, "application/json", self.securities[security])
        raise AssertionError(url)


def _source(transport: MapTransport, symbols: tuple[str, ...] = ("SBER", "LKOH")) -> MoexCorporateActionsSource:
    return MoexCorporateActionsSource(transport=transport, clock=lambda: CLOCK, symbols=symbols)


def _live_transport() -> MapTransport:
    gate = fixture_bytes("cci_subscriber_gate.html")
    empty = fixture_bytes("bondization_empty.json")
    return MapTransport(
        cci={"SBER": gate, "LKOH": gate},
        securities={
            "SBER": fixture_bytes("sber_securities_dividends.json"),
            "LKOH": fixture_bytes("lkoh_securities_dividends.json"),
        },
        bondization={"SBER": empty, "LKOH": empty},
    )


def _dividend_table(rows: list[list[object]], columns: list[str] | None = None) -> bytes:
    header = columns or [
        "secid",
        "registryclosedate",
        "value",
        "currencyid",
        "coupondate",
    ]
    payload = {"dividends": {"columns": header, "data": rows}}
    return json.dumps(payload).encode("utf-8")


def test_live_probe_note_is_counts_not_a_dividend_sample() -> None:
    note = json.loads((FIXTURES / "probe_note.json").read_text(encoding="utf-8"))
    assert note["dividend_rows_sber_lkoh"] == 0
    assert note["pit_class"] == "RESEARCH_ONLY"
    assert note["announcement_timestamp_present"] is False
    candle = next(item for item in note["endpoints"] if "history/" in item["url"])
    assert candle["dividend_rows"] == 0
    assert candle["sber_candle_cursor_total"] != note["dividend_rows_sber_lkoh"]


def test_live_fixtures_stay_blocked_without_backdating() -> None:
    transport = _live_transport()
    source = _source(transport)
    artifacts = source.fetch_sample(limit=40)
    assert len(artifacts) == 2
    observations = []
    for artifact in artifacts:
        assert artifact.fetch_status == FetchStatus.FORBIDDEN
        assert artifact.historical_pit_quality == PitQuality.RESEARCH_ONLY
        assert artifact.published_at is None
        assert artifact.published_at_precision == PublishedAtPrecision.UNKNOWN
        assert artifact.event_date is None
        assert artifact.first_observed_at == CLOCK
        assert artifact.quality_status == RecordQuality.UNRESOLVED
        assert artifact.historical_pit_quality != PitQuality.PIT_VERIFIED
        assert "cci_corp_actions_dividends_subscriber_only" in artifact.limitations
        assert any("moex_iss_securities_dividends_rejected" in note for note in artifact.limitations)
        assert any("bondization_empty_coupons=0" in note for note in artifact.limitations)
        assert "announcement_timestamp_absent" in artifact.limitations
        raw = transport.cci[artifact.entity_identifiers["requested_secid"]]
        parsed = source.parse(artifact, raw)
        assert parsed == ()
        observations.extend(parsed)
    assert observations == []
    coverage = source.inspect_coverage()
    assert coverage.status == AdapterStatus.BLOCKED
    assert coverage.earliest is None
    assert coverage.latest is None


def test_description_value_and_candle_close_are_not_dividends() -> None:
    candle = fixture_bytes("history_dividends_candle.json")
    transport = MapTransport(
        cci={"SBER": fixture_bytes("cci_subscriber_gate.html")},
        securities={"SBER": candle},
        bondization={"SBER": fixture_bytes("bondization_empty.json")},
    )
    source = _source(transport, symbols=("SBER",))
    artifact = source.fetch_sample(limit=40)[0]
    parsed = source.parse(artifact, transport.cci["SBER"])
    assert parsed == ()
    assert any("candles" in note for note in artifact.limitations)
    description = json.loads(fixture_bytes("sber_securities_dividends.json"))
    face = next(row for row in description["description"]["data"] if row[0] == "FACEVALUE")
    assert face[2] == "3"
    assert all(item.value != 3 for item in parsed)
    assert all(item.value != 270.1 for item in parsed)


def test_registry_close_is_not_announcement_and_clock_is_not_backdated() -> None:
    body = _dividend_table([["SBER", "2024-07-11", 34, "SUR", "2024-07-18"]])
    transport = MapTransport(cci={"SBER": body})
    source = _source(transport, symbols=("SBER",))
    artifact = source.fetch_sample(limit=40)[0]
    assert artifact.event_date == date(2024, 7, 11)
    assert artifact.published_at is None
    assert artifact.historical_pit_quality == PitQuality.RESEARCH_ONLY
    assert artifact.first_observed_at == CLOCK
    assert artifact.first_observed_at.date() != artifact.event_date
    assert artifact.quality_status == RecordQuality.ACCEPTED
    observation = source.parse(artifact, body)[0]
    assert observation.extra["registry_close_date"] == "2024-07-11"
    assert observation.extra["announcement_at"] is None
    assert observation.extra["payment_date"] == "2024-07-18"
    assert observation.currency == "RUB"
    assert observation.value == 34
    assert "/securities/" not in "".join(transport.calls)


def test_announcement_timestamp_is_proxy_and_does_not_replace_registry_close() -> None:
    columns = ["secid", "registryclosedate", "value", "currencyid", "announcement_timestamp"]
    body = _dividend_table(
        [["LKOH", "2024-12-20", 514, "RUB", "2024-12-01T10:00:00+00:00"]],
        columns=columns,
    )
    source = _source(MapTransport(cci={"LKOH": body}), symbols=("LKOH",))
    artifact = source.fetch_sample(limit=40)[0]
    assert artifact.event_date == date(2024, 12, 20)
    assert artifact.published_at == datetime(2024, 12, 1, 10, 0, tzinfo=UTC)
    assert artifact.published_at_precision == PublishedAtPrecision.TIMESTAMP
    assert artifact.historical_pit_quality == PitQuality.PIT_PROXY
    assert artifact.first_observed_at == CLOCK
    assert artifact.chronology_errors() == ()
    observation = source.parse(artifact, body)[0]
    assert observation.extra["registry_close_date"] != observation.extra["announcement_at"]


def test_date_only_announcement_is_pit_proxy() -> None:
    columns = ["secid", "recorddate", "value", "announcement_date"]
    body = _dividend_table([["sber", "2024-07-11", 34, "2024-06-01"]], columns=columns)
    source = _source(MapTransport(cci={"SBER": body}), symbols=("SBER",))
    artifact = source.fetch_sample(limit=40)[0]
    assert artifact.event_date == date(2024, 7, 11)
    assert artifact.published_at == datetime(2024, 6, 1, tzinfo=UTC)
    assert artifact.published_at_precision == PublishedAtPrecision.DATE_ONLY
    assert artifact.historical_pit_quality == PitQuality.PIT_PROXY
    assert artifact.first_observed_at == CLOCK


def test_future_announcement_does_not_backdate_first_observed_at() -> None:
    columns = ["secid", "registryclosedate", "value", "announcement_timestamp"]
    body = _dividend_table(
        [["SBER", "2024-07-11", 34, "2026-10-13T00:00:00+00:00"]],
        columns=columns,
    )
    source = _source(MapTransport(cci={"SBER": body}), symbols=("SBER",))
    artifact = source.fetch_sample(limit=40)[0]
    assert artifact.first_observed_at == CLOCK
    assert artifact.published_at == datetime(2026, 10, 13, tzinfo=UTC)
    assert "first_observed_at_precedes_published_at" in artifact.chronology_errors()
    assert artifact.quality_status == RecordQuality.UNRESOLVED


def test_ambiguous_identity_stays_unresolved() -> None:
    body = json.dumps(
        {
            "dividends": {
                "columns": ["secid", "registryclosedate", "value", "currencyid", "isin"],
                "data": [
                    ["SBERP", "2024-07-11", 1, "RUB", None],
                    ["", "2024-07-11", 1, "RUB", None],
                    ["SBER", "2024-07-11", 1, "RUB", "RU0009024277"],
                    ["Сбербанк", "2024-07-11", 1, "RUB", "RU0009029540"],
                ],
            }
        }
    ).encode("utf-8")
    source = _source(MapTransport(cci={"SBER": body}), symbols=("SBER",))
    artifacts = source.fetch_sample(limit=40)
    assert len(artifacts) == 4
    assert all(item.quality_status == RecordQuality.UNRESOLVED for item in artifacts)
    parsed = [source.parse(item, body)[0] for item in artifacts]
    assert all(item.quality_status == RecordQuality.UNRESOLVED for item in parsed)
    assert all(item.issuer_identity == {} for item in parsed)
    assert all(item.quality_status != RecordQuality.ACCEPTED for item in parsed)


def test_bondization_recorddate_stays_apart_from_coupondate() -> None:
    payload = {
        "coupons": {
            "columns": ["secid", "isin", "recorddate", "coupondate", "value", "faceunit"],
            "data": [["SBER", "RU0009029540", "2024-07-11", "2024-07-18", 34, "RUB"]],
        },
        "amortizations": {"columns": ["secid"], "data": []},
        "offers": {"columns": ["secid"], "data": []},
    }
    bond = json.dumps(payload).encode("utf-8")
    foreign = {
        "coupons": {
            "columns": ["secid", "recorddate", "coupondate", "value", "faceunit"],
            "data": [["SU26238RMFS4", "2021-12-07", "2021-12-08", 34.04, "RUB"]],
        },
        "amortizations": {"columns": ["secid"], "data": []},
        "offers": {"columns": ["secid"], "data": []},
    }
    transport = MapTransport(
        cci={"SBER": b"{}", "LKOH": b"{}"},
        securities={
            "SBER": fixture_bytes("sber_securities_dividends.json"),
            "LKOH": fixture_bytes("lkoh_securities_dividends.json"),
        },
        bondization={"SBER": bond, "LKOH": json.dumps(foreign).encode("utf-8")},
    )
    source = _source(transport)
    artifacts = source.fetch_sample(limit=40)
    by_symbol = {item.entity_identifiers["requested_secid"]: item for item in artifacts}
    sber = by_symbol["SBER"]
    assert sber.event_date == date(2024, 7, 11)
    assert sber.published_at is None
    assert sber.historical_pit_quality == PitQuality.RESEARCH_ONLY
    assert sber.first_observed_at == CLOCK
    observation = source.parse(sber, bond)[0]
    assert observation.metric_id == "corporate_action.coupon"
    assert observation.extra["registry_close_date"] == "2024-07-11"
    assert observation.extra["payment_date"] == "2024-07-18"
    assert observation.value == 34
    assert any(note.startswith("bondization_known_at:CURRENT_STATE_ONLY") for note in sber.limitations)
    assert by_symbol["LKOH"].quality_status == RecordQuality.UNRESOLVED
    assert by_symbol["LKOH"].entity_identifiers["secid"] == "SU26238RMFS4"


def test_sample_caps_at_forty_records() -> None:
    rows = [["SBER", f"2020-01-{(index % 28) + 1:02d}", 10 + index, "RUB", None] for index in range(45)]
    body = _dividend_table(rows)
    source = _source(MapTransport(cci={"SBER": body}), symbols=("SBER",))
    artifacts = source.fetch_sample(limit=100)
    assert len(artifacts) == SAMPLE_CAP
    assert any(note == "truncated_to_40" for note in artifacts[-1].limitations)
    assert source.fetch_range(start=date(2020, 1, 1), end=date(2020, 1, 2), limit=40)
    outside = source.fetch_range(start=date(2024, 1, 1), end=date(2024, 1, 31), limit=40)
    assert outside == ()


def test_fetch_range_uses_registry_close_not_announcement() -> None:
    columns = ["secid", "registryclosedate", "value", "announcement_date"]
    body = _dividend_table(
        [
            ["SBER", "2024-07-11", 34, "2024-01-15"],
            ["LKOH", "2024-01-20", 10, "2024-07-01"],
        ],
        columns=columns,
    )
    transport = MapTransport(cci={"SBER": body, "LKOH": body})
    source = _source(transport)
    july = source.fetch_range(start=date(2024, 7, 1), end=date(2024, 7, 31), limit=40)
    assert [item.entity_identifiers["requested_secid"] for item in july] == ["SBER"]
    assert july[0].event_date == date(2024, 7, 11)
    january = source.fetch_range(start=date(2024, 1, 1), end=date(2024, 1, 31), limit=40)
    assert [item.entity_identifiers["requested_secid"] for item in january] == ["LKOH"]


def test_explicit_zero_is_marked_and_validate_rejects_accepted_without_evidence() -> None:
    body = _dividend_table([["SBER", "2024-07-11", 0, "RUB", None]])
    source = _source(MapTransport(cci={"SBER": body}), symbols=("SBER",))
    artifact = source.fetch_sample(limit=40)[0]
    observation = source.parse(artifact, body)[0]
    assert observation.value == 0
    assert "explicit_zero" in observation.limitations
    assert observation.quality_errors() == ()
    broken = source.validate(
        (
            observation.__class__(
                metric_id=observation.metric_id,
                source_id=observation.source_id,
                content_hash=observation.content_hash,
                normalization_version=observation.normalization_version,
                quality_status=RecordQuality.ACCEPTED,
                value=1,
            ),
        )
    )
    assert broken[0].quality_status == RecordQuality.QUARANTINE


def test_source_does_not_target_polza_or_prospective_writes() -> None:
    text = SOURCE_PATH.read_text(encoding="utf-8").casefold()
    assert "polza" not in text
    assert "prospective_captures" not in text
    assert "committee_decisions" not in text
    assert "signal_outputs" not in text
