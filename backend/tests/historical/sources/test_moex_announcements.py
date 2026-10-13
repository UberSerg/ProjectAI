"""Offline MOEX-07 access check. These tests do not call ISS."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    PitQuality,
    PublishedAtPrecision,
)
from app.modules.historical.sources.moex_announcements.source import (
    SAMPLE_CAP,
    SOURCE_ID,
    FetchResponse,
    MoexAnnouncementsSource,
    assess_announcements,
    fixture_bytes,
)

CLOCK = datetime(2026, 10, 13, 5, 40, tzinfo=UTC)
ANTIBOT_HTML = b"""<!DOCTYPE html><html><body>
<h1>Forbidden</h1>
<p id="request-id">redacted</p>
<p id="request-ip">redacted</p>
</body></html>
"""


class MapTransport:
    def __init__(self, body: bytes, *, content_type: str = "application/json", status: int = 200) -> None:
        self.body = body
        self.content_type = content_type
        self.status = status
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str]) -> FetchResponse:
        self.calls.append((url, dict(params)))
        return FetchResponse(self.status, self.content_type, self.body)


def test_ir_calendar_keeps_metadata_and_does_not_invent_published_at() -> None:
    batch = assess_announcements(fixture_bytes("ir_calendar_page.json"), first_observed_at=CLOCK)
    assert batch.adapter_status is AdapterStatus.PARTIAL
    assert batch.fetch_status is FetchStatus.OK
    assert batch.same_as_sitenews is False
    assert batch.overlap_with_sitenews == 0
    assert len(batch.artifacts) == SAMPLE_CAP
    assert "not_sitenews" in batch.limitations
    assert "no_published_at" in batch.limitations
    item = batch.artifacts[0]
    assert item.source_id == SOURCE_ID
    assert item.document_type == "ir_calendar_event"
    assert item.title == "Выплаты по инструментам: Погашение выпуска 001PS-01"
    assert item.source_url == "https://mgkl.group/investors/events/"
    assert item.entity_identifiers == {"secid": "MGKL"}
    assert item.external_document_id == "323"
    assert item.published_at is None
    assert item.event_date is None
    assert item.published_at != item.first_observed_at
    assert item.first_observed_at == CLOCK
    assert item.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert item.published_at_precision is PublishedAtPrecision.UNKNOWN
    assert item.historical_availability_evidence is None
    assert "event_date_is_not_publication" in item.limitations
    assert "update_time_is_not_published_at" in item.limitations
    assert "2026-05-05" not in (item.title or "")
    assert "2030-11-20" not in repr(item)
    assert item.chronology_errors() == ()


def test_calendar_caps_at_twenty_and_ignores_schedule_clocks() -> None:
    payload = json.loads(fixture_bytes("ir_calendar_page.json"))
    row = list(payload["cci_ir_calendar"]["data"][0])
    columns = payload["cci_ir_calendar"]["columns"]
    id_at = columns.index("event_id")
    rows = []
    for index in range(25):
        copied = list(row)
        copied[id_at] = str(1000 + index)
        rows.append(copied)
    payload["cci_ir_calendar"]["data"] = rows
    batch = assess_announcements(
        json.dumps(payload).encode(),
        first_observed_at=CLOCK,
        limit=100,
    )
    assert len(batch.artifacts) == SAMPLE_CAP
    assert all(item.published_at is None for item in batch.artifacts)
    assert all(item.event_date is None for item in batch.artifacts)


def test_explicit_published_at_is_moscow_proxy_and_not_the_fetch_clock() -> None:
    payload = {
        "cci_ir_calendar": {
            "columns": ["secid", "event_id", "event_type_name", "event_link", "event_date", "published_at"],
            "data": [
                [
                    "SBER",
                    "9",
                    "Дивиденды",
                    "https://issuer.example/events/9",
                    "2030-01-01",
                    "2026-10-01 12:00:00",
                ]
            ],
        }
    }
    item = assess_announcements(json.dumps(payload).encode(), first_observed_at=CLOCK).artifacts[0]
    assert item.published_at == datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    assert item.published_at != item.first_observed_at
    assert item.event_date is None
    assert item.historical_pit_quality is PitQuality.PIT_PROXY
    assert item.published_at_precision is PublishedAtPrecision.TIMESTAMP
    assert item.historical_availability_evidence == "moex_cci_ir_calendar_published_at"
    assert item.entity_identifiers == {"secid": "SBER"}
    assert item.chronology_errors() == ()


def test_long_description_is_not_stored() -> None:
    secret = "SECRET-BODY-" * 40
    payload = {
        "cci_ir_calendar": {
            "columns": ["event_id", "event_type_name", "event_description", "event_link", "secid"],
            "data": [["1", "Событие", secret, "https://issuer.example/a", "LKOH"]],
        }
    }
    batch = assess_announcements(json.dumps(payload).encode(), first_observed_at=CLOCK)
    assert batch.artifacts[0].title == "Событие"
    assert secret not in repr(batch)


def test_sitenews_json_is_not_a_new_archive() -> None:
    payload = {
        "sitenews": {
            "columns": ["id", "title", "published_at"],
            "data": [[105055, "Risk params", "2026-10-12 22:35:47"], [105053, "Other", "2026-10-12 22:33:53"]],
        }
    }
    batch = assess_announcements(json.dumps(payload).encode(), first_observed_at=CLOCK)
    assert batch.same_as_sitenews is True
    assert batch.artifacts == ()
    assert batch.overlap_with_sitenews == 2
    assert batch.fetch_status is FetchStatus.UNSUPPORTED
    assert "not_a_new_archive" in batch.limitations
    assert "Risk params" not in repr(batch)


def test_listing_rss_links_are_the_same_sitenews_archive() -> None:
    secret = "SECRET BODY must not be stored"
    items = []
    for index in range(1, 8):
        items.append(
            f"<item><title>Headline {index}</title>"
            f"<link>https://www.moex.com/n{105000 + index}</link>"
            f"<description>{secret} {index}</description></item>"
        )
    payload = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<rss version="2.0"><channel><title>Новости листинга</title>'
        "<link>https://moex.com/</link>" + "".join(items) + "</channel></rss>"
    ).encode()
    batch = assess_announcements(payload, first_observed_at=CLOCK, limit=100)
    assert batch.same_as_sitenews is True
    assert batch.artifacts == ()
    assert batch.overlap_with_sitenews == 7
    assert secret not in repr(batch)
    assert "Headline" not in repr(batch)


def test_subscriber_gate_is_blocked() -> None:
    batch = assess_announcements(
        fixture_bytes("cci_subscriber_gate.html"),
        first_observed_at=CLOCK,
        http_status=200,
        content_type="text/html",
    )
    assert batch.adapter_status is AdapterStatus.BLOCKED
    assert batch.fetch_status is FetchStatus.FORBIDDEN
    assert batch.artifacts == ()
    assert batch.same_as_sitenews is False
    assert "subscriber_only" in batch.limitations


def test_antibot_shell_is_blocked() -> None:
    batch = assess_announcements(ANTIBOT_HTML, first_observed_at=CLOCK, http_status=403)
    assert batch.adapter_status is AdapterStatus.BLOCKED
    assert batch.fetch_status is FetchStatus.UNSUPPORTED
    assert batch.artifacts == ()
    assert "antibot_shell" in batch.limitations


def test_source_requests_the_calendar_and_does_not_backdate_the_window() -> None:
    transport = MapTransport(fixture_bytes("ir_calendar_page.json"))
    source = MoexAnnouncementsSource(transport=transport, clock=lambda: CLOCK)
    coverage = source.inspect_coverage()
    assert coverage.status is AdapterStatus.PARTIAL
    assert coverage.earliest is None
    assert coverage.latest is None
    assert transport.calls == [
        (
            "https://iss.moex.com/iss/cci/calendars/ir-calendar.json",
            {"limit": "20", "iss.meta": "off"},
        )
    ]
    assert "sitenews" not in transport.calls[0][0]
    sample = source.fetch_sample(limit=100)
    assert len(sample) == SAMPLE_CAP
    assert source.fetch_range(start=date(2029, 1, 1), end=date(2030, 12, 31), limit=20) == ()
    assert source.parse(sample[0], b"SECRET BODY") == ()


def test_recorded_probe_matches_the_calendar_fixture() -> None:
    note = json.loads(fixture_bytes("probe_note.json"))
    batch = assess_announcements(fixture_bytes("ir_calendar_page.json"), first_observed_at=CLOCK)
    assert note["task"] == "MOEX-07"
    assert note["honest_status"] == "PARTIAL"
    assert note["pit"] == "RESEARCH_ONLY"
    assert note["http_status"] == 200
    assert note["item_count"] == 20
    assert note["overlap_with_sitenews"] == 0
    assert note["same_as_sitenews"] is False
    assert note["published_at_present"] is False
    assert "ir-calendar" in note["primary_url"]
    assert note["sitenews_archive"]["ingested_as_moex_07"] is False
    assert note["sitenews_archive"]["listing_links_are_sitenews_ids"] == 20
    assert note["sitenews_archive"]["overlap_with_latest_sitenews_page"] == 8
    assert note["sitenews_archive"]["body_stored"] is False
    assert note["blocked"][0]["reason"] == "subscriber_only"
    assert len(batch.artifacts) == note["item_count"]
    assert batch.overlap_with_sitenews == note["overlap_with_sitenews"]
    assert all(item.historical_pit_quality is PitQuality.RESEARCH_ONLY for item in batch.artifacts)
    assert all(item.published_at is None for item in batch.artifacts)
