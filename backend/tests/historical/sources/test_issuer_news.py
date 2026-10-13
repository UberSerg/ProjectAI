"""Offline issuer-news metadata and the pure dedup key. No live download."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    PitQuality,
    PublishedAtPrecision,
)
from app.modules.historical.sources.issuer_news.dedup import (
    DEDUP_KEY_FIELDS,
    issuer_news_dedup_key,
)
from app.modules.historical.sources.issuer_news.fetch import (
    assert_listing_url,
    fetch_lukoil_press_metadata,
)
from app.modules.historical.sources.issuer_news.listing import (
    MAX_ITEMS,
    SOURCE_DISCOVERY,
    SOURCE_METADATA,
    news_01_coverage,
    parse_lukoil_press_listing,
    parse_lukoil_press_pages,
)

OBSERVED = datetime(2026, 10, 13, 5, 30, tzinfo=UTC)
FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "modules"
    / "historical"
    / "sources"
    / "issuer_news"
    / "fixtures"
    / "lkoh_press_listing.html"
)
PROBE = FIXTURE.with_name("live_probe.json").parent.parent / "live_probe.json"
SECRET = "SECRET BODY must not be stored"

ANTIBOT_HTML = b"""<!DOCTYPE html>
<html><body>
  <h1>Forbidden</h1>
  <p id="REQUEST-DATE">Datetime: redacted</p>
  <p id="REQUEST-IP">redacted</p>
  <p id="REQUEST-ID">redacted</p>
  <a href='https://lukoil.ru/PressCenter/Pressreleases/Pressrelease/not-a-card' class='wrap-link'>
  <h2><span class="date">09.10.2026 - </span><span class="title">Must not be read</span></h2></a>
</body></html>
"""


def _card(slug: str, title: str, when: str = "09.10.2026") -> str:
    return (
        f"<a href='https://lukoil.ru/PressCenter/Pressreleases/Pressrelease/{slug}' class='wrap-link'>"
        f"<h2><span class=\"date\">{when} - </span><span class=\"title\">{title}</span></h2></a>"
        f"<div class=\"panel-body\"><p>{SECRET} {slug}</p></div>"
    )


def test_dedup_key_fields_are_source_identity_and_published_date() -> None:
    assert DEDUP_KEY_FIELDS == ("source", "external_id_or_canonical_url", "published_date")
    keyed = issuer_news_dedup_key(
        source="NEWS-03",
        external_id="laiavozhskoe",
        url="https://lukoil.ru/PressCenter/Pressreleases/Pressrelease/other",
        published_on=date(2026, 10, 9),
    )
    assert keyed.source == "NEWS-03"
    assert keyed.identity_kind == "external_id"
    assert keyed.identity == "laiavozhskoe"
    assert keyed.published_on == date(2026, 10, 9)
    assert keyed.as_token() == "NEWS-03|external_id|laiavozhskoe|2026-10-09"


def test_dedup_key_uses_canonical_url_when_external_id_is_absent() -> None:
    left = issuer_news_dedup_key(
        source="NEWS-03",
        url="HTTPS://Lukoil.ru/PressCenter/Pressreleases/Pressrelease/slug/?utm_source=x#frag",
        published_on=date(2026, 10, 9),
    )
    right = issuer_news_dedup_key(
        source="NEWS-03",
        url="https://lukoil.ru/PressCenter/Pressreleases/Pressrelease/slug",
        published_on=date(2026, 10, 9),
    )
    assert left.identity_kind == "canonical_url"
    assert left.identity == right.identity
    assert left.as_token() == right.as_token()


def test_dedup_key_changes_with_published_date_and_refuses_a_clock() -> None:
    first = issuer_news_dedup_key(source="NEWS-03", external_id="slug", published_on=date(2026, 10, 9))
    second = issuer_news_dedup_key(source="NEWS-03", external_id="slug", published_on=date(2026, 9, 28))
    undated = issuer_news_dedup_key(source="NEWS-03", external_id="slug")
    assert first.as_token() != second.as_token()
    assert undated.published_on is None
    assert undated.as_token().endswith("|")
    with pytest.raises(TypeError):
        issuer_news_dedup_key(
            source="NEWS-03",
            external_id="slug",
            published_on=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        issuer_news_dedup_key(source=" ", url="https://lukoil.ru/x")
    with pytest.raises(ValueError):
        issuer_news_dedup_key(source="NEWS-03")


def test_dedup_module_does_not_download() -> None:
    from app.modules.historical.sources.issuer_news import dedup, listing

    for module in (dedup, listing):
        text = Path(module.__file__).read_text(encoding="utf-8").lower()
        assert "urlopen" not in text
        assert "httpx" not in text


def test_listing_keeps_title_url_and_civil_date_and_drops_teaser() -> None:
    payload = _card("laiavozhskoe-neftegazokondensatnoe-mestorozhdenie", "Лайявожское месторождение").encode()
    batch = parse_lukoil_press_listing(payload, first_observed_at=OBSERVED)
    assert batch.fetch_status is FetchStatus.OK
    assert batch.adapter_status is AdapterStatus.READY
    assert batch.pit == "PIT_PROXY"
    assert len(batch.artifacts) == 1
    item = batch.artifacts[0]
    assert item.source_id == SOURCE_METADATA
    assert item.document_type == "issuer_press_metadata"
    assert item.title == "Лайявожское месторождение"
    assert item.source_url.endswith("/laiavozhskoe-neftegazokondensatnoe-mestorozhdenie")
    assert item.external_document_id == "laiavozhskoe-neftegazokondensatnoe-mestorozhdenie"
    assert item.published_at == datetime(2026, 10, 9, tzinfo=UTC)
    assert item.published_at_precision is PublishedAtPrecision.DATE_ONLY
    assert item.historical_pit_quality is PitQuality.PIT_PROXY
    assert item.historical_availability_evidence == "lukoil_press_listing_civil_date"
    assert item.entity_identifiers["secid"] == "LKOH"
    assert "article_body_not_fetched" in item.limitations
    assert SECRET not in repr(batch)
    assert item.chronology_errors() == ()
    coverage = news_01_coverage(batch)
    assert coverage.source_id == SOURCE_DISCOVERY
    assert coverage.status is AdapterStatus.READY
    assert coverage.earliest == date(2026, 10, 9)
    assert coverage.latest == date(2026, 10, 9)


def test_missing_or_invalid_date_is_research_only() -> None:
    payload = (
        _card("undated", "No clock", when="")
        + _card("bad-date", "Bad clock", when="32.13.2026")
    ).encode()
    batch = parse_lukoil_press_listing(payload, first_observed_at=OBSERVED)
    assert batch.adapter_status is AdapterStatus.PARTIAL
    assert batch.pit == "RESEARCH_ONLY"
    assert all(item.published_at is None for item in batch.artifacts)
    assert all(item.historical_pit_quality is PitQuality.RESEARCH_ONLY for item in batch.artifacts)
    assert all(item.chronology_errors() == () for item in batch.artifacts)
    coverage = news_01_coverage(batch)
    assert coverage.earliest is None
    assert coverage.latest is None


def test_cap_is_twenty_and_duplicate_urls_collapse() -> None:
    cards = "".join(_card(f"item-{index}", f"Headline {index}", when="01.09.2026") for index in range(1, 26))
    cards += _card("item-1", "Duplicate title", when="02.09.2026")
    batch = parse_lukoil_press_listing(cards.encode(), first_observed_at=OBSERVED, limit=100)
    assert len(batch.artifacts) == MAX_ITEMS
    assert batch.artifacts[0].title == "Headline 1"
    assert batch.artifacts[0].external_document_id == "item-1"
    assert "Duplicate title" not in repr(batch)
    assert SECRET not in repr(batch)


def test_pages_merge_until_the_cap() -> None:
    first = "".join(_card(f"a-{index}", f"A {index}") for index in range(10)).encode()
    second = "".join(_card(f"b-{index}", f"B {index}") for index in range(10)).encode()
    extra = _card("c-0", "C 0").encode()
    batch = parse_lukoil_press_pages((first, second, extra), first_observed_at=OBSERVED)
    assert len(batch.artifacts) == MAX_ITEMS
    assert batch.artifacts[0].external_document_id == "a-0"
    assert batch.artifacts[-1].external_document_id == "b-9"


def test_antibot_shell_is_blocked_and_not_parsed_as_news() -> None:
    batch = parse_lukoil_press_listing(ANTIBOT_HTML, first_observed_at=OBSERVED)
    assert batch.artifacts == ()
    assert batch.fetch_status is FetchStatus.UNSUPPORTED
    assert batch.adapter_status is AdapterStatus.BLOCKED
    assert batch.pit == "BLOCKED"
    assert "Must not be read" not in repr(batch)
    assert news_01_coverage(batch).status is AdapterStatus.BLOCKED


def test_cloudflare_challenge_is_blocked() -> None:
    payload = b"<html><title>Just a moment...</title><body>cf-browser-verification</body></html>"
    batch = parse_lukoil_press_listing(payload, first_observed_at=OBSERVED)
    assert batch.adapter_status is AdapterStatus.BLOCKED
    assert batch.artifacts == ()


def test_article_url_is_refused_and_fetch_stays_on_listing_pages() -> None:
    with pytest.raises(ValueError, match="article_fetch_refused"):
        assert_listing_url(
            "https://lukoil.ru/PressCenter/Pressreleases/Pressrelease/laiavozhskoe-neftegazokondensatnoe-mestorozhdenie"
        )
    calls: list[str] = []

    def transport(url: str) -> tuple[int, bytes]:
        calls.append(url)
        skip = "skip=10" in url
        slugs = [f"b-{index}" for index in range(10)] if skip else [f"a-{index}" for index in range(10)]
        body = "".join(_card(slug, slug) for slug in slugs).encode()
        return 200, body

    probe = fetch_lukoil_press_metadata(first_observed_at=OBSERVED, transport=transport)
    assert probe.http_status == 200
    assert len(probe.pages) == 2
    assert all(page.http_status == 200 for page in probe.pages)
    assert len(probe.batch.artifacts) == MAX_ITEMS
    assert calls == [
        "https://lukoil.ru/PressCenter/Pressreleases?skip=0&take=10",
        "https://lukoil.ru/PressCenter/Pressreleases?skip=10&take=10",
    ]
    assert all("/Pressrelease/" not in url for url in calls)
    assert SECRET not in repr(probe.batch)


def test_saved_listing_fixture_is_metadata_only() -> None:
    raw = FIXTURE.read_bytes()
    assert len(raw) < 100_000
    assert SECRET.encode() in raw
    batch = parse_lukoil_press_listing(raw, first_observed_at=OBSERVED)
    assert len(batch.artifacts) == MAX_ITEMS
    assert batch.pit == "PIT_PROXY"
    assert batch.adapter_status is AdapterStatus.READY
    assert all(item.published_at is not None for item in batch.artifacts)
    assert all(item.published_at_precision is PublishedAtPrecision.DATE_ONLY for item in batch.artifacts)
    assert batch.artifacts[0].external_document_id == "laiavozhskoe-neftegazokondensatnoe-mestorozhdenie"
    assert batch.artifacts[0].published_at == datetime(2026, 10, 9, tzinfo=UTC)
    assert SECRET not in repr(batch)
    assert news_01_coverage(batch).source_id == "NEWS-01"
    probe = PROBE.read_text(encoding="utf-8")
    assert '"article_bodies_fetched": false' in probe
    assert '"http_status": 200' in probe
