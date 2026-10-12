"""MOEX headline metadata. Article bodies are not fetched."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from app.modules.historical.domain.evidence import (
    FetchStatus,
    HistoricalArtifact,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.disclosure.classify import PARSER_VERSION, is_antibot_shell
from app.modules.intelligence.news.rss import parse_feed

# Same clock the production MOEX sitenews adapter documents: naive ISS timestamps are Moscow.
_MSK = timezone(timedelta(hours=3), name="Europe/Moscow")
HEADLINE_LIMIT = 20
_NEWS_SOURCE = "NEWS-02"


@dataclass(frozen=True, slots=True)
class HeadlineBatch:
    source_id: str
    artifacts: tuple[HistoricalArtifact, ...]
    fetch_status: FetchStatus
    limitations: tuple[str, ...]


def headlines_from_moex_sitenews(
    payload: bytes,
    *,
    first_observed_at: datetime,
    limit: int = HEADLINE_LIMIT,
) -> HeadlineBatch:
    """ISS `sitenews.json` rows already used by intelligence.news. Metadata only."""
    if is_antibot_shell(payload):
        return _blocked_batch()
    cap = _cap(limit)
    try:
        data = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HeadlineBatch(
            source_id=_NEWS_SOURCE,
            artifacts=(),
            fetch_status=FetchStatus.FAILED,
            limitations=("malformed_json",),
        )
    block = data.get("sitenews") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return HeadlineBatch(
            source_id=_NEWS_SOURCE,
            artifacts=(),
            fetch_status=FetchStatus.FAILED,
            limitations=("missing_sitenews_block",),
        )
    columns = block.get("columns") or []
    rows = block.get("data") or []
    if not isinstance(columns, list) or not isinstance(rows, list):
        return HeadlineBatch(
            source_id=_NEWS_SOURCE,
            artifacts=(),
            fetch_status=FetchStatus.FAILED,
            limitations=("malformed_sitenews_shape",),
        )
    artifacts: list[HistoricalArtifact] = []
    for row in rows:
        if len(artifacts) >= cap:
            break
        if not isinstance(row, list):
            continue
        record = {str(columns[i]): row[i] for i in range(min(len(columns), len(row)))}
        news_id = record.get("id")
        if news_id is None:
            continue
        title = _clean_title(record.get("title"))
        url = f"https://www.moex.com/n{news_id}"
        published = _parse_moex_naive(record.get("published_at"))
        artifacts.append(
            _headline(
                external_id=str(news_id),
                title=title,
                url=url,
                published_at=published,
                first_observed_at=first_observed_at,
                evidence="moex_iss_sitenews_published_at" if published is not None else None,
            )
        )
    return _ok_batch(tuple(artifacts))


def headlines_from_moex_rss(
    payload: bytes,
    *,
    first_observed_at: datetime,
    limit: int = HEADLINE_LIMIT,
) -> HeadlineBatch:
    """RSS 2.0 headline metadata. `description` / `content:encoded` are discarded."""
    if is_antibot_shell(payload):
        return _blocked_batch()
    cap = _cap(limit)
    stripped = _clip_rss(payload.lstrip(b"\xef\xbb\xbf"), cap)
    if not _looks_like_rss(stripped):
        return HeadlineBatch(
            source_id=_NEWS_SOURCE,
            artifacts=(),
            fetch_status=FetchStatus.UNSUPPORTED,
            limitations=("not_rss", "not_a_filing"),
        )
    parsed = parse_feed(stripped)
    if not parsed.items and parsed.parse_warnings:
        return HeadlineBatch(
            source_id=_NEWS_SOURCE,
            artifacts=(),
            fetch_status=FetchStatus.FAILED,
            limitations=tuple(parsed.parse_warnings),
        )
    artifacts: list[HistoricalArtifact] = []
    for item in parsed.items:
        if len(artifacts) >= cap:
            break
        url = (item.link or "").strip()
        if not url:
            continue
        title = _clean_title(item.title)
        published = item.published_at
        external_id = (item.guid or url).strip()
        artifacts.append(
            _headline(
                external_id=external_id,
                title=title,
                url=url,
                published_at=published,
                first_observed_at=first_observed_at,
                evidence="moex_rss_pubdate" if published is not None else None,
            )
        )
    return _ok_batch(tuple(artifacts))


def _headline(
    *,
    external_id: str,
    title: str | None,
    url: str,
    published_at: datetime | None,
    first_observed_at: datetime,
    evidence: str | None,
) -> HistoricalArtifact:
    if published_at is None:
        pit = PitQuality.RESEARCH_ONLY
        precision = PublishedAtPrecision.UNKNOWN
        limitations = ("metadata_only", "article_body_not_fetched", "missing_published_at_research_only")
    else:
        pit = PitQuality.PIT_PROXY
        precision = PublishedAtPrecision.TIMESTAMP
        limitations = ("metadata_only", "article_body_not_fetched", "publisher_clock_is_not_backfilled")
    stamp = published_at.isoformat() if published_at is not None else ""
    digest = hashlib.sha256(f"{title or ''}\n{url}\n{stamp}".encode()).hexdigest()
    return HistoricalArtifact(
        source_id=_NEWS_SOURCE,
        source_url=url,
        external_document_id=external_id,
        document_type="news_headline",
        content_hash=digest,
        parser_version=PARSER_VERSION,
        fetch_status=FetchStatus.OK,
        first_observed_at=first_observed_at,
        title=title,
        published_at=published_at,
        published_at_precision=precision,
        historical_availability_evidence=evidence,
        historical_pit_quality=pit,
        quality_status=RecordQuality.UNRESOLVED,
        limitations=limitations,
    )


def _ok_batch(artifacts: tuple[HistoricalArtifact, ...]) -> HeadlineBatch:
    status = FetchStatus.OK if artifacts else FetchStatus.EMPTY
    return HeadlineBatch(
        source_id=_NEWS_SOURCE,
        artifacts=artifacts,
        fetch_status=status,
        limitations=("metadata_only", "article_body_not_fetched", f"capped_at_{HEADLINE_LIMIT}"),
    )


def _blocked_batch() -> HeadlineBatch:
    return HeadlineBatch(
        source_id=_NEWS_SOURCE,
        artifacts=(),
        fetch_status=FetchStatus.UNSUPPORTED,
        limitations=("antibot_shell", "not_a_filing"),
    )


def _cap(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, HEADLINE_LIMIT)


def _clean_title(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_moex_naive(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        naive = datetime.fromisoformat(text)
    except ValueError:
        return None
    if naive.tzinfo is None:
        return naive.replace(tzinfo=_MSK).astimezone(UTC)
    return naive.astimezone(UTC)


def _looks_like_rss(payload: bytes) -> bool:
    head = payload.lstrip()[:600].lower()
    if head.startswith(b"<?xml"):
        return b"<rss" in head or b"<feed" in head or b"<rdf" in head
    return head.startswith((b"<rss", b"<feed", b"<rdf"))


def _clip_rss(payload: bytes, limit: int) -> bytes:
    """Keep a bounded prefix of complete items so a multi-megabyte export is not required."""
    lowered = payload.lower()
    needle = b"</item>"
    pos = 0
    end = -1
    found = 0
    while found < limit:
        idx = lowered.find(needle, pos)
        if idx < 0:
            break
        found += 1
        end = idx + len(needle)
        pos = end
    if found == 0 or end < 0:
        return payload
    if found < limit and b"</channel>" in lowered:
        return payload
    chunk = payload[:end]
    if b"</channel>" not in chunk.lower():
        chunk += b"</channel></rss>"
    return chunk
