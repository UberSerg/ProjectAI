"""Adapter + idempotent persist behavior (in-process, mocked HTTP / session)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import httpx

from app.modules.intelligence.news.adapters.base import FetchedDocument
from app.modules.intelligence.news.adapters.cbr_rss import CbrRssAdapter
from app.modules.intelligence.news.adapters.moex_sitenews import MoexSitenewsAdapter
from app.modules.intelligence.news.http import NewsHttpClient
from app.modules.intelligence.news.registry import get_source
from app.modules.intelligence.news.repository import PersistOutcome, persist_document

_CBR_RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Press</title>
<item>
  <title>Rate decision</title>
  <link>https://www.cbr.ru/press/PR/?file=1.htm</link>
  <guid>docid_99</guid>
  <pubDate>Wed, 07 Oct 2026 12:10:00 +0300</pubDate>
  <description>Text body</description>
</item>
</channel></rss>
"""

_MOEX_JSON = b"""{
  "sitenews": {
    "columns": ["id", "tag", "title", "published_at", "modified_at"],
    "data": [
      [104898, "site", "MOEX headline", "2026-10-07 13:25:02", "2026-10-07 13:25:11"]
    ]
  }
}"""


def test_cbr_adapter_maps_source_document_fields() -> None:
    source = get_source("cbr_press_ru")
    client = NewsHttpClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=_CBR_RSS)),
        max_retries=0,
    )
    result = CbrRssAdapter().fetch(source, client)
    client.close()
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.provider == "cbr"
    assert doc.source_type == "PRESS_RELEASE"
    assert doc.canonical_url is not None
    assert doc.published_at is not None
    assert doc.observed_at is not None
    assert doc.known_at >= doc.observed_at
    assert doc.content_hash
    assert doc.metadata["known_at_basis"] in {"MAX_PUBLISHED_OBSERVED", "OBSERVED_AT"}


def test_moex_adapter_parses_iss_json() -> None:
    source = get_source("moex_sitenews")
    client = NewsHttpClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=_MOEX_JSON)),
        max_retries=0,
    )
    result = MoexSitenewsAdapter().fetch(source, client)
    client.close()
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.provider == "moex"
    assert doc.external_id == "104898"
    assert "moex.com/n104898" in (doc.canonical_url or "")
    assert doc.metadata["published_at_tz"].startswith("Europe/Moscow")


def test_moex_malformed_json_soft() -> None:
    source = get_source("moex_sitenews")
    client = NewsHttpClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"{not-json")),
        max_retries=0,
    )
    result = MoexSitenewsAdapter().fetch(source, client)
    client.close()
    assert result.documents == ()
    assert result.warnings[0].startswith("malformed_json")


def _doc(hash_suffix: str = "aaa", key: str = "cbr|url|https://www.cbr.ru/x") -> FetchedDocument:
    now = datetime.now(UTC)
    return FetchedDocument(
        document_key=key,
        provider="cbr",
        source_type="PRESS_RELEASE",
        canonical_url="https://www.cbr.ru/x",
        title="T",
        published_at=now,
        observed_at=now,
        known_at=now,
        content_hash="0" * 60 + hash_suffix[:4],
        language="ru",
        raw_text="body",
        metadata={"source_id": "cbr_press_ru"},
    )


def test_persist_duplicate_hash_idempotent() -> None:
    existing = MagicMock()
    existing.id = 10
    existing.revision = 1
    session = MagicMock()
    session.scalar.return_value = existing
    outcome = persist_document(session, _doc())
    assert outcome.status == "duplicate_hash"
    session.add.assert_not_called()


def test_persist_revision_on_new_hash() -> None:
    latest = MagicMock()
    latest.id = 11
    latest.revision = 2
    latest.content_hash = "old_hash"
    session = MagicMock()
    # first scalar: hash lookup → None; second: latest by key → latest
    session.scalar.side_effect = [None, latest]
    session.add = MagicMock()
    session.flush = MagicMock()

    # Capture added row
    added: list[Any] = []

    def _add(row: Any) -> None:
        row.id = 99
        added.append(row)

    session.add.side_effect = _add
    outcome = persist_document(session, _doc(hash_suffix="bbbb"))
    assert outcome.status == "revised"
    assert outcome.revision == 3
    assert added[0].revision == 3


def test_persist_outcome_dataclass() -> None:
    o = PersistOutcome(
        status="inserted",
        document_id=1,
        revision=1,
        content_hash="abc",
        document_key="k",
    )
    assert o.status == "inserted"
