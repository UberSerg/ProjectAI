"""DISC access: anti-bot HTML is blocked and is not a filing."""

from datetime import UTC, datetime

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    PitQuality,
    PublishedAtPrecision,
)
from app.modules.historical.sources.disclosure.classify import (
    blocked_shell_artifact,
    classify_disclosure_payload,
    is_antibot_shell,
    parse_filings,
)
from app.modules.historical.sources.disclosure.headlines import (
    HEADLINE_LIMIT,
    headlines_from_moex_rss,
    headlines_from_moex_sitenews,
)

OBSERVED = datetime(2026, 10, 12, 20, 23, tzinfo=UTC)

ANTIBOT_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body>
  <div style="text-align: center;">
    <h1>Forbidden</h1>
    <p id="REQUEST-DATE">Datetime: redacted</p>
    <p id="REQUEST-IP">redacted</p>
    <p id="REQUEST-ID">redacted</p>
    <p id="ORIGIN-ID">Origin: redacted</p>
    <p>ПАО Сбербанк дивиденд 10.5 руб. на обыкновенную акцию</p>
  </div>
</body></html>
""".encode()

PORTAL_HTML = """<!DOCTYPE html><html><body><h1>Раскрытие</h1>
<p>Существенный факт. Дивиденд 10.5</p></body></html>""".encode()


def test_antibot_fixture_is_blocked_unsupported_and_not_a_filing() -> None:
    assert is_antibot_shell(ANTIBOT_HTML)
    verdict = classify_disclosure_payload(
        "DISC-01",
        ANTIBOT_HTML,
        http_status=403,
        content_type="text/html",
    )
    assert verdict.adapter_status is AdapterStatus.BLOCKED
    assert verdict.fetch_status is FetchStatus.UNSUPPORTED
    assert verdict.readable is False
    assert verdict.is_filing is False
    assert "antibot_shell" in verdict.limitations
    filings = parse_filings(ANTIBOT_HTML)
    assert filings == ()
    artifact = blocked_shell_artifact(
        source_id="DISC-01",
        source_url="https://www.e-disclosure.ru/portal/event.aspx?EventId=1",
        body=ANTIBOT_HTML,
        first_observed_at=OBSERVED,
    )
    assert artifact.fetch_status is FetchStatus.UNSUPPORTED
    assert artifact.document_type == "antibot_shell"
    assert artifact.published_at is None
    assert artifact.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert artifact.title is None
    assert "10.5" not in (artifact.title or "")
    assert artifact.chronology_errors() == ()


def test_plain_portal_html_is_not_parsed_as_a_filing() -> None:
    assert is_antibot_shell(PORTAL_HTML) is False
    verdict = classify_disclosure_payload("DISC-02", PORTAL_HTML, http_status=200, content_type="text/html")
    assert verdict.fetch_status is FetchStatus.UNSUPPORTED
    assert verdict.is_filing is False
    assert parse_filings(PORTAL_HTML) == ()


def test_machine_readable_feed_is_not_a_corporate_filing() -> None:
    payload = b'{"sitenews": {"columns": ["id"], "data": []}}'
    verdict = classify_disclosure_payload("NEWS-02", payload, http_status=200, content_type="application/json")
    assert verdict.fetch_status is FetchStatus.OK
    assert verdict.readable is True
    assert verdict.is_filing is False
    assert parse_filings(payload) == ()


def test_sitenews_keeps_title_url_and_moscow_published_at() -> None:
    payload = b"""
    {"sitenews": {"columns": ["id", "tag", "title", "published_at", "modified_at"],
      "data": [[105055, "site", "Risk params", "2026-10-12 22:35:47", "2026-10-12 22:36:00"]]}}
    """
    batch = headlines_from_moex_sitenews(payload, first_observed_at=OBSERVED)
    assert batch.fetch_status is FetchStatus.OK
    assert len(batch.artifacts) == 1
    item = batch.artifacts[0]
    assert item.document_type == "news_headline"
    assert item.title == "Risk params"
    assert item.source_url == "https://www.moex.com/n105055"
    assert item.published_at == datetime(2026, 10, 12, 19, 35, 47, tzinfo=UTC)
    assert item.published_at != item.first_observed_at
    assert item.historical_pit_quality is PitQuality.PIT_PROXY
    assert item.published_at_precision is PublishedAtPrecision.TIMESTAMP
    assert item.historical_availability_evidence == "moex_iss_sitenews_published_at"
    assert "article_body_not_fetched" in item.limitations


def test_missing_published_at_is_research_only_and_not_backdated() -> None:
    payload = b"""
    {"sitenews": {"columns": ["id", "title", "published_at"],
      "data": [[7, "No clock", null]]}}
    """
    item = headlines_from_moex_sitenews(payload, first_observed_at=OBSERVED).artifacts[0]
    assert item.published_at is None
    assert item.published_at != item.first_observed_at
    assert item.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert item.published_at_precision is PublishedAtPrecision.UNKNOWN
    assert item.historical_availability_evidence is None
    assert "missing_published_at_research_only" in item.limitations
    assert item.chronology_errors() == ()


def test_rss_stores_metadata_only_and_caps_at_twenty() -> None:
    items = []
    for index in range(1, 26):
        items.append(
            f"<item><title>Headline {index}</title>"
            f"<link>https://www.moex.com/n{index}</link>"
            f"<pubDate>Mon, 12 Oct 2026 12:00:{index:02d} +0300</pubDate>"
            f"<description>SECRET BODY {index} must not be stored</description>"
            f"</item>"
        )
    payload = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<rss version="2.0"><channel><title>MOEX</title>' + "".join(items) + "</channel></rss>"
    ).encode()
    batch = headlines_from_moex_rss(payload, first_observed_at=OBSERVED, limit=100)
    assert len(batch.artifacts) == HEADLINE_LIMIT
    first = batch.artifacts[0]
    assert first.title == "Headline 1"
    assert first.source_url == "https://www.moex.com/n1"
    assert first.published_at == datetime(2026, 10, 12, 9, 0, 1, tzinfo=UTC)
    rendered = repr(batch)
    assert "SECRET BODY" not in rendered
    assert all("SECRET BODY" not in (item.title or "") for item in batch.artifacts)


def test_rss_without_pubdate_is_research_only() -> None:
    payload = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item><title>Undated</title><link>https://www.moex.com/n9</link></item>
    </channel></rss>
    """
    item = headlines_from_moex_rss(payload, first_observed_at=OBSERVED).artifacts[0]
    assert item.published_at is None
    assert item.historical_pit_quality is PitQuality.RESEARCH_ONLY
    assert item.first_observed_at == OBSERVED


def test_truncated_rss_prefix_keeps_complete_items_only() -> None:
    payload = (
        b'<?xml version="1.0"?><rss version="2.0"><channel>'
        b"<item><title>Kept</title><link>https://www.moex.com/n1</link>"
        b"<pubDate>Mon, 12 Oct 2026 12:00:00 +0300</pubDate></item>"
        b"<item><title>Cut mid"
    )
    batch = headlines_from_moex_rss(payload, first_observed_at=OBSERVED)
    assert len(batch.artifacts) == 1
    assert batch.artifacts[0].title == "Kept"
    assert "Cut mid" not in repr(batch)


def test_antibot_shell_is_not_parsed_as_headlines() -> None:
    batch = headlines_from_moex_rss(ANTIBOT_HTML, first_observed_at=OBSERVED)
    assert batch.artifacts == ()
    assert batch.fetch_status is FetchStatus.UNSUPPORTED
    news = headlines_from_moex_sitenews(ANTIBOT_HTML, first_observed_at=OBSERVED)
    assert news.artifacts == ()
    assert news.fetch_status is FetchStatus.UNSUPPORTED
