"""DISC-03 metadata dedup. Offline: no network, no filing parse."""

from datetime import UTC, datetime
from pathlib import Path

import app.modules.historical.sources.disclosure_meta as disclosure_meta_module
from app.modules.historical.sources.disclosure_meta import (
    DEDUP_DESIGN_STATUS,
    DISCOVER_STATUS,
    dedupe_disclosure_metadata,
    disclosure_meta,
    shares_canonical_url,
)

PUBLISHED = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)

ANTIBOT_HTML = """<!DOCTYPE html>
<html><body>
  <h1>Forbidden</h1>
  <p id="REQUEST-DATE">Datetime: redacted</p>
  <p id="REQUEST-IP">redacted</p>
  <p id="REQUEST-ID">redacted</p>
  <p>ПАО Сбербанк дивиденд 10.5 руб.</p>
</body></html>
""".encode()

PORTAL_HTML = "<!DOCTYPE html><html><body><h1>Раскрытие</h1><p>дивиденд 10.5</p></body></html>".encode()


def test_same_canonical_url_is_a_duplicate_and_first_record_wins() -> None:
    first = disclosure_meta(
        title="  Board recommendation  ",
        url="https://WWW.E-DISCLOSURE.RU/portal/event.aspx?utm_source=x&EventId=1&b=2#frag",
        published_at=PUBLISHED,
        external_id="ext-1",
    )
    second = disclosure_meta(
        title="Later title",
        url="https://www.e-disclosure.ru/portal/event.aspx?b=2&EventId=1",
        published_at=LATER,
        external_id="ext-2",
    )
    assert first is not None and second is not None
    assert first.canonical_url == "https://www.e-disclosure.ru/portal/event.aspx?EventId=1&b=2"
    assert first.canonical_url == second.canonical_url
    assert first.title == "Board recommendation"
    assert first.published_at == PUBLISHED
    assert shares_canonical_url(first, second)
    kept = dedupe_disclosure_metadata([first, second])
    assert kept == (first,)
    assert kept[0].external_id == "ext-1"
    assert kept[0].dedup_key == first.canonical_url


def test_distinct_urls_stay_separate_even_with_the_same_title_and_external_id() -> None:
    shared = dict(title="Same headline", published_at=PUBLISHED, external_id="ext-9")
    left = disclosure_meta(url="https://www.e-disclosure.ru/portal/event.aspx?EventId=1", **shared)
    right = disclosure_meta(url="https://www.e-disclosure.ru/portal/event.aspx?EventId=2", **shared)
    apex = disclosure_meta(url="https://e-disclosure.ru/portal/event.aspx?EventId=1", **shared)
    insecure = disclosure_meta(url="http://www.e-disclosure.ru/portal/event.aspx?EventId=1", **shared)
    slashed = disclosure_meta(url="https://www.e-disclosure.ru/portal/event.aspx/?EventId=1", **shared)
    assert left is not None and right is not None and apex is not None
    assert insecure is not None and slashed is not None
    rows = (left, right, apex, insecure, slashed)
    assert dedupe_disclosure_metadata(rows) == rows
    assert shares_canonical_url(left, right) is False
    assert shares_canonical_url(left, apex) is False


def test_missing_url_is_not_collapsed_by_external_id_or_title() -> None:
    first = disclosure_meta(title="Untitled", url="  ", published_at=None, external_id=" same ")
    second = disclosure_meta(title="Untitled", url=None, published_at=PUBLISHED, external_id="same")
    assert first is not None and second is not None
    assert first.canonical_url is None
    assert first.external_id == "same"
    assert first.dedup_key is None
    assert shares_canonical_url(first, second) is False
    assert dedupe_disclosure_metadata([first, second]) == (first, second)


def test_antibot_shell_is_not_a_filing_and_receives_no_id() -> None:
    refused = disclosure_meta(
        title="ПАО Сбербанк дивиденд 10.5 руб.",
        url="https://www.e-disclosure.ru/portal/event.aspx?EventId=1",
        published_at=PUBLISHED,
        external_id="filing-99",
        body=ANTIBOT_HTML,
    )
    assert refused is None
    real = disclosure_meta(
        title="Kept metadata",
        url="https://www.e-disclosure.ru/portal/event.aspx?EventId=7",
        published_at=PUBLISHED,
        external_id="ext-7",
        body=PORTAL_HTML,
    )
    assert real is not None
    assert real.external_id == "ext-7"
    assert real.title == "Kept metadata"
    assert "10.5" not in (real.title or "")
    kept = dedupe_disclosure_metadata([item for item in (refused, real) if item is not None])
    assert kept == (real,)
    assert "filing-99" not in repr(kept)


def test_discover_stays_blocked_and_the_module_does_not_fetch() -> None:
    assert DISCOVER_STATUS == "BLOCKED"
    assert DEDUP_DESIGN_STATUS == "READY"
    source = Path(disclosure_meta_module.__file__).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "urlopen" not in source
    assert "requests" not in source
