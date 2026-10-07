"""Allowlist + SSRF + known_at + hashing + RSS parse tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.modules.intelligence.news.hashing import canonical_url, content_hash, document_key
from app.modules.intelligence.news.http import NewsHttpClient, NewsHttpError
from app.modules.intelligence.news.known_at import compute_known_at
from app.modules.intelligence.news.registry import get_source, list_sources
from app.modules.intelligence.news.rss import parse_feed


def test_allowlist_has_production_sources() -> None:
    ids = {s.source_id for s in list_sources()}
    assert "cbr_press_ru" in ids
    assert "moex_sitenews" in ids
    assert get_source("cbr_press_ru").provider == "cbr"


def test_unknown_source_rejected() -> None:
    with pytest.raises(KeyError):
        get_source("https://evil.example/rss")


def test_ssrf_blocks_non_allowlisted_host() -> None:
    source = get_source("cbr_press_ru")
    client = NewsHttpClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"ok")))
    with pytest.raises(NewsHttpError, match="SSRF"):
        client.fetch_bytes(source, url="https://127.0.0.1/secret")
    with pytest.raises(NewsHttpError, match="SSRF"):
        client.fetch_bytes(source, url="https://evil.example/rss")
    client.close()


def test_allowlisted_fetch_ok() -> None:
    source = get_source("cbr_press_ru")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "ProjectAI-IntelligenceNews" in request.headers["User-Agent"]
        return httpx.Response(200, content=b"<rss/>")

    client = NewsHttpClient(transport=httpx.MockTransport(handler), max_retries=0)
    assert client.fetch_bytes(source) == b"<rss/>"
    client.close()


def test_known_at_does_not_backdate_past_publication() -> None:
    observed = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    published = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    known, basis = compute_known_at(
        policy="MAX_PUBLISHED_OBSERVED",
        published_at=published,
        observed_at=observed,
    )
    assert known == observed
    assert basis == "MAX_PUBLISHED_OBSERVED"


def test_known_at_uses_future_publication_claim() -> None:
    observed = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    published = observed + timedelta(hours=2)
    known, _ = compute_known_at(
        policy="MAX_PUBLISHED_OBSERVED",
        published_at=published,
        observed_at=observed,
    )
    assert known == published


def test_known_at_missing_published() -> None:
    observed = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    known, basis = compute_known_at(
        policy="MAX_PUBLISHED_OBSERVED",
        published_at=None,
        observed_at=observed,
    )
    assert known == observed
    assert basis == "OBSERVED_AT"


def test_canonical_url_and_hash_stable() -> None:
    a = canonical_url("https://WWW.Example.com/path?utm_source=x&b=2&a=1#frag")
    b = canonical_url("https://www.example.com/path?a=1&b=2")
    assert a == b
    h1 = content_hash(title="T", body=" body  ", canonical=a)
    h2 = content_hash(title="T", body="body", canonical=b)
    assert h1 == h2
    assert document_key(provider="cbr", canonical=a, external_id=None).startswith("cbr|url|")


def test_malformed_feed_soft_fail() -> None:
    parsed = parse_feed(b"not xml at all <<<")
    assert parsed.items == ()
    assert parsed.parse_warnings
    assert parsed.parse_warnings[0].startswith("malformed_xml")


def test_rss_parses_item() -> None:
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel>
      <title>Test</title>
      <item>
        <title>Hello</title>
        <link>https://www.cbr.ru/press/1</link>
        <guid>docid_1</guid>
        <pubDate>Wed, 07 Oct 2026 12:10:00 +0300</pubDate>
        <description>Body</description>
      </item>
      <item><title>Broken</title></item>
    </channel></rss>
    """
    parsed = parse_feed(xml)
    assert parsed.title == "Test"
    assert len(parsed.items) == 2
    assert parsed.items[0].title == "Hello"
    assert parsed.items[0].published_at is not None
    assert parsed.items[0].published_at.tzinfo is not None
