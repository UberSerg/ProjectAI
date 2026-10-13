"""CBR-10 / CBR-11 list metadata. Offline: the live check is the saved fixture."""

from __future__ import annotations

import ast
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.modules.historical.domain.evidence import AdapterStatus, FetchStatus, PitQuality
from app.modules.historical.sources.cbr_news import ITEM_CAP, CbrNewsSource
from app.modules.historical.sources.cbr_news.catalog import SPECS

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "modules"
    / "historical"
    / "sources"
    / "cbr_news"
    / "fixtures"
    / "access_check.json"
)
SOURCE_DIR = FIXTURE.parents[1]
OBSERVED = datetime(2026, 10, 13, 5, 37, 35, tzinfo=UTC)
PRESS_PUBLISHED = datetime(2026, 10, 8, 8, 0, tzinfo=UTC)
ACT_PUBLISHED = datetime(2026, 10, 12, 8, 7, tzinfo=UTC)


def _probe() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _rss(items: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<rss version="2.0"><channel><title>CBR</title>{items}</channel></rss>'
    ).encode()


def test_fixture_is_metadata_only_and_small() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    assert FIXTURE.stat().st_size < 100_000
    assert '"description"' not in raw
    assert "SECRET" not in raw
    probe = _probe()
    assert probe["probed_at"] == OBSERVED.isoformat()
    assert set(probe["sources"]) == {"CBR-10", "CBR-11"}


def test_cbr10_press_access_check_keeps_title_url_and_pubdate() -> None:
    block = _probe()["sources"]["CBR-10"]
    assert block["list_url"] == "https://www.cbr.ru/rss/RssPress"
    assert block["discovered_from"] == "https://www.cbr.ru/development/RSS/"
    assert block["http_status"] == 200
    assert block["content_type"] == "application/rss+xml"
    assert block["item_count_in_feed"] == 14
    assert block["published_at_in_payload"] is True
    assert len(block["items"]) == 14

    source = CbrNewsSource("CBR-10")
    access = source.access
    assert access.task_status == "READY"
    assert access.adapter_status is AdapterStatus.READY
    assert access.http_status == 200
    assert access.published_at_in_payload is True
    assert access.item_count_in_feed == 14
    assert len(access.artifacts) == 14
    assert "http_status=200" in access.limitations
    assert "article_body_not_fetched" in access.limitations

    item = access.artifacts[0]
    assert item.document_type == "press_headline"
    assert item.title.startswith("Установлены факты манипулирования")
    assert item.source_url == "https://www.cbr.ru/press/PR/?file=639270476049988487PNP.htm"
    assert item.published_at == PRESS_PUBLISHED
    assert item.first_observed_at == OBSERVED
    assert item.published_at != item.first_observed_at
    assert item.historical_pit_quality is PitQuality.PIT_PROXY
    assert item.historical_availability_evidence == "cbr_rss_pubdate"
    assert item.chronology_errors() == ()
    assert item.entity_identifiers["http_status"] == "200"
    coverage = source.inspect_coverage()
    assert coverage.status is AdapterStatus.READY
    assert coverage.latest == date(2026, 10, 8)
    assert coverage.earliest == date(2026, 9, 14)


def test_cbr11_regulatory_feed_is_capped_and_files_are_not_stored() -> None:
    block = _probe()["sources"]["CBR-11"]
    assert block["list_url"] == "https://www.cbr.ru/rss/navr"
    assert block["discovered_from"] == "https://www.cbr.ru/analytics/na_vr/"
    assert block["http_status"] == 200
    assert block["published_at_in_payload"] is True
    assert block["item_count_in_feed"] == 1000
    assert len(block["items"]) == ITEM_CAP

    source = CbrNewsSource("CBR-11")
    access = source.access
    assert access.task_status == "READY"
    assert access.http_status == 200
    assert access.item_count_in_feed == 1000
    assert len(source.fetch_sample(limit=100)) == ITEM_CAP
    assert "act_file_not_downloaded" in access.limitations
    item = access.artifacts[0]
    assert item.document_type == "regulatory_headline"
    assert item.title == (
        "7383-У от 25.06.2026 Указание Банка России «О внесении изменений "
        "в Указание Банка России от 17 августа 2022 года № 6222-У»"
    )
    assert "\n" not in (item.title or "")
    assert item.source_url == "https://www.cbr.ru/Queries/UniDbQuery/File/90134/8599"
    assert item.published_at == ACT_PUBLISHED
    assert item.historical_pit_quality is PitQuality.PIT_PROXY
    assert "act_file_not_downloaded" in item.limitations
    assert item.chronology_errors() == ()
    assert source.parse(item, b"<description>act body</description>") == ()


def test_discover_reports_the_official_url_and_does_not_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("discover must not open a socket")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    for source_id, spec in SPECS.items():
        coverage = CbrNewsSource(source_id).discover()
        assert coverage.status is AdapterStatus.READY
        assert coverage.earliest is None
        assert coverage.latest is None
        assert f"list_url={spec.list_url}" in coverage.limitations
        assert "discover_does_not_fetch" in coverage.limitations


def test_parser_caps_at_twenty_and_drops_descriptions() -> None:
    rows = []
    for index in range(1, 26):
        rows.append(
            "<item>"
            f"<title>Headline {index}</title>"
            f"<link>https://www.cbr.ru/press/PR/?file={index}</link>"
            f"<pubDate>Mon, 12 Oct 2026 12:00:{index:02d} +0300</pubDate>"
            f"<description>SECRET BODY {index}</description>"
            "</item>"
        )
    access = CbrNewsSource.from_response(
        "CBR-10",
        b"\xef\xbb\xbf" + _rss("".join(rows)),
        http_status=200,
        content_type="application/rss+xml",
        observed_at=OBSERVED,
    ).access
    assert access.task_status == "READY"
    assert access.item_count_in_feed == 25
    assert len(access.artifacts) == ITEM_CAP
    assert access.published_at_in_payload is True
    assert access.artifacts[0].title == "Headline 1"
    assert access.artifacts[0].published_at == datetime(2026, 10, 12, 9, 0, 1, tzinfo=UTC)
    rendered = repr(access)
    assert "SECRET BODY" not in rendered
    assert "Headline 21" not in rendered


def test_missing_pubdate_is_research_only_even_if_the_title_contains_a_date() -> None:
    payload = _rss(
        "<item><title>Undated note (08.10.2026)</title>" "<link>https://www.cbr.ru/press/PR/?file=1</link></item>"
    )
    access = CbrNewsSource.from_response(
        "CBR-10",
        payload,
        http_status=200,
        content_type="application/rss+xml",
        observed_at=OBSERVED,
    ).access
    assert access.task_status == "RESEARCH_ONLY"
    assert access.published_at_in_payload is False
    item = access.artifacts[0]
    assert item.published_at is None
    assert item.first_observed_at == OBSERVED
    assert item.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert "missing_published_at_research_only" in item.limitations
    assert item.chronology_errors() == ()


def test_unparsed_pubdate_stays_research_only() -> None:
    payload = _rss(
        "<item><title>Broken clock</title>"
        "<link>https://www.cbr.ru/press/PR/?file=1</link>"
        "<pubDate>not-a-date</pubDate></item>"
    )
    access = CbrNewsSource.from_response(
        "CBR-10",
        payload,
        http_status=200,
        content_type="application/rss+xml",
        observed_at=OBSERVED,
    ).access
    assert access.published_at_in_payload is True
    assert access.task_status == "RESEARCH_ONLY"
    assert access.artifacts[0].published_at is None


def test_html_list_page_is_blocked_with_http_status_and_is_not_scraped() -> None:
    html = b"""<!DOCTYPE html><html><body>
      <h1>SECRET TITLE 08.10.2026</h1>
      <a href="https://www.cbr.ru/press/PR/?file=1">SECRET TITLE</a>
    </body></html>"""
    access = CbrNewsSource.from_response(
        "CBR-11",
        html,
        http_status=200,
        content_type="text/html; charset=utf-8",
        observed_at=OBSERVED,
    ).access
    assert access.task_status == "BLOCKED"
    assert access.adapter_status is AdapterStatus.BLOCKED
    assert access.http_status == 200
    assert access.fetch_status is FetchStatus.UNSUPPORTED
    assert "http_status=200" in access.limitations
    assert "not_a_machine_readable_list" in access.limitations
    assert access.artifacts[0].title is None
    assert access.artifacts[0].document_type == "access_check"
    assert "SECRET TITLE" not in repr(access)


def test_forbidden_and_missing_lists_are_blocked_with_their_status() -> None:
    denied = CbrNewsSource.from_response(
        "CBR-10",
        b"",
        http_status=403,
        content_type="text/html",
        observed_at=OBSERVED,
    ).access
    assert denied.task_status == "BLOCKED"
    assert denied.http_status == 403
    assert denied.fetch_status is FetchStatus.FORBIDDEN
    assert "http_status=403" in denied.limitations

    missing = CbrNewsSource.from_response(
        "CBR-11",
        b"not found",
        http_status=404,
        observed_at=OBSERVED,
    ).access
    assert missing.task_status == "BLOCKED"
    assert missing.http_status == 404
    assert "http_status=404" in missing.limitations


def test_server_error_is_failed_not_a_dated_sample() -> None:
    access = CbrNewsSource.from_response(
        "CBR-10",
        b"",
        http_status=503,
        observed_at=OBSERVED,
    ).access
    assert access.task_status == "FAILED"
    assert access.http_status == 503
    assert access.adapter_status is AdapterStatus.FAILED
    assert access.artifacts[0].published_at is None


def test_malformed_rss_is_failed() -> None:
    access = CbrNewsSource.from_response(
        "CBR-10",
        b"<?xml version='1.0'?><rss><channel><item><title>Cut",
        http_status=200,
        content_type="application/rss+xml",
        observed_at=OBSERVED,
    ).access
    assert access.task_status == "FAILED"
    assert "malformed_xml" in access.limitations
    assert access.http_status == 200


def test_future_pubdate_is_not_clamped_to_the_observation_clock() -> None:
    payload = _rss(
        "<item><title>Later</title><link>https://www.cbr.ru/press/PR/?file=9</link>"
        "<pubDate>Wed, 14 Oct 2026 12:00:00 +0300</pubDate></item>"
    )
    item = CbrNewsSource.from_response(
        "CBR-10",
        payload,
        http_status=200,
        content_type="application/rss+xml",
        observed_at=OBSERVED,
    ).access.artifacts[0]
    assert item.published_at == datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
    assert item.first_observed_at == OBSERVED
    assert "first_observed_at_precedes_published_at" in item.chronology_errors()


def test_fetch_range_uses_pubdate_and_parse_adds_no_metric() -> None:
    source = CbrNewsSource("CBR-10")
    day = source.fetch_range(start=date(2026, 10, 8), end=date(2026, 10, 8), limit=20)
    assert len(day) == 1
    assert day[0].published_at == PRESS_PUBLISHED
    assert source.fetch_range(start=date(2026, 1, 1), end=date(2026, 1, 2), limit=20) == ()
    with pytest.raises(ValueError, match="end precedes start"):
        source.fetch_range(start=date(2026, 10, 8), end=date(2026, 10, 7), limit=20)
    assert source.parse(day[0], b"raw-list") == ()
    assert source.validate(()) == ()


def test_package_does_not_fetch() -> None:
    for path in SOURCE_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert all(name.split(".")[0] not in {"httpx", "requests", "urllib"} for name in names)
