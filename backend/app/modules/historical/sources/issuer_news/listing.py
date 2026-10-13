"""Lukoil press-listing metadata. Article bodies and teasers are not stored.

The official listing is HTML, not RSS:
``https://lukoil.ru/PressCenter/Pressreleases``.
Each card exposes a civil date, a title, and a release URL. There is no clock,
so publication time is ``DATE_ONLY`` and PIT is ``PIT_PROXY``.
A page without those dates stays ``RESEARCH_ONLY``. An anti-bot shell is
``BLOCKED`` and is not parsed as news.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from app.modules.historical.application.adapter import CoverageReport
from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    HistoricalArtifact,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)
from app.modules.historical.sources.disclosure.classify import is_antibot_shell
from app.modules.historical.sources.issuer_news.dedup import issuer_news_dedup_key

SOURCE_DISCOVERY = "NEWS-01"
SOURCE_METADATA = "NEWS-03"
PARSER_VERSION = "issuer_news_lukoil_listing_v1"
ISSUER = "LKOH"
MAX_ITEMS = 20
LISTING_URL = "https://lukoil.ru/PressCenter/Pressreleases"

_CARD = re.compile(
    r"<a\s+href=(?P<q>['\"])(?P<href>https://lukoil\.ru/PressCenter/Pressreleases/Pressrelease/[^'\"]+)(?P=q)"
    r"(?P<attrs>[^>]*)>\s*<h2>\s*"
    r"<span\s+class=\"date\">(?P<date>.*?)</span>\s*"
    r"<span\s+class=\"title\">(?P<title>.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
_DMY = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_BLOCK_MARKERS = (
    b"cf-browser-verification",
    b"just a moment",
    b"g-recaptcha",
    b"/captcha/",
)


@dataclass(frozen=True, slots=True)
class IssuerNewsBatch:
    issuer: str
    listing_url: str
    artifacts: tuple[HistoricalArtifact, ...]
    fetch_status: FetchStatus
    adapter_status: AdapterStatus
    limitations: tuple[str, ...]

    @property
    def pit(self) -> str:
        if self.adapter_status is AdapterStatus.BLOCKED:
            return "BLOCKED"
        if not self.artifacts:
            return "RESEARCH_ONLY"
        if all(item.historical_pit_quality is PitQuality.PIT_PROXY for item in self.artifacts):
            return "PIT_PROXY"
        return "RESEARCH_ONLY"


def news_01_coverage(batch: IssuerNewsBatch) -> CoverageReport:
    """NEWS-01 discovery view of a metadata batch. Does not fetch."""
    dates = [item.published_at.date() for item in batch.artifacts if item.published_at is not None]
    return CoverageReport(
        source_id=SOURCE_DISCOVERY,
        status=batch.adapter_status,
        earliest=min(dates) if dates else None,
        latest=max(dates) if dates else None,
        formats=("html_listing_metadata",),
        limitations=batch.limitations,
    )


def parse_lukoil_press_listing(
    payload: bytes,
    *,
    first_observed_at: datetime,
    limit: int = MAX_ITEMS,
) -> IssuerNewsBatch:
    """Parse one listing page. ``panel-body`` teasers are ignored."""
    return parse_lukoil_press_pages(
        (payload,),
        first_observed_at=first_observed_at,
        limit=limit,
    )


def parse_lukoil_press_pages(
    pages: tuple[bytes, ...] | list[bytes],
    *,
    first_observed_at: datetime,
    limit: int = MAX_ITEMS,
) -> IssuerNewsBatch:
    """Merge listing pages, cap at 20, and keep the first card for each URL."""
    observed = _require_aware(first_observed_at)
    cap = _cap(limit)
    if not pages:
        return _empty_batch(("no_listing_pages",))
    if all(is_blocked_listing(page) for page in pages):
        return blocked_listing_batch()
    artifacts: list[HistoricalArtifact] = []
    seen: set[str] = set()
    saw_blocked = False
    for page in pages:
        if is_blocked_listing(page):
            saw_blocked = True
            continue
        for card in _cards(page):
            if card.url in seen:
                continue
            seen.add(card.url)
            artifacts.append(_artifact(card, observed))
            if len(artifacts) >= cap:
                break
        if len(artifacts) >= cap:
            break
    limitations = ["metadata_only", "article_body_not_fetched", f"capped_at_{MAX_ITEMS}"]
    if saw_blocked:
        limitations.append("later_page_blocked")
    if not artifacts:
        return _empty_batch(tuple(limitations + ["no_listing_cards"]))
    if any(item.published_at is None for item in artifacts):
        status = AdapterStatus.PARTIAL
        limitations.append("missing_published_at_research_only")
    else:
        status = AdapterStatus.READY
        limitations.append("listing_civil_date_not_a_timestamp")
    return IssuerNewsBatch(
        issuer=ISSUER,
        listing_url=LISTING_URL,
        artifacts=tuple(artifacts),
        fetch_status=FetchStatus.OK,
        adapter_status=status,
        limitations=tuple(limitations),
    )


@dataclass(frozen=True, slots=True)
class _Card:
    url: str
    external_id: str
    title: str | None
    published_on: date | None


def _cards(payload: bytes) -> tuple[_Card, ...]:
    text = payload.decode("utf-8", errors="replace")
    cards: list[_Card] = []
    for match in _CARD.finditer(text):
        url = html.unescape(match.group("href")).strip()
        external_id = _slug(url)
        if not external_id:
            continue
        title = _plain(match.group("title"))
        cards.append(
            _Card(
                url=url,
                external_id=external_id,
                title=title,
                published_on=_civil_date(match.group("date")),
            )
        )
    return tuple(cards)


def _artifact(card: _Card, observed: datetime) -> HistoricalArtifact:
    if card.published_on is None:
        published_at = None
        precision = PublishedAtPrecision.UNKNOWN
        pit = PitQuality.RESEARCH_ONLY
        evidence = None
        limitations = ("metadata_only", "article_body_not_fetched", "missing_published_at_research_only")
    else:
        published_at = datetime(
            card.published_on.year,
            card.published_on.month,
            card.published_on.day,
            tzinfo=UTC,
        )
        precision = PublishedAtPrecision.DATE_ONLY
        pit = PitQuality.PIT_PROXY
        evidence = "lukoil_press_listing_civil_date"
        limitations = ("metadata_only", "article_body_not_fetched", "listing_civil_date_not_a_timestamp")
    key = issuer_news_dedup_key(
        source=SOURCE_METADATA,
        external_id=card.external_id,
        url=card.url,
        published_on=card.published_on,
    )
    digest = hashlib.sha256(key.as_token().encode("utf-8")).hexdigest()
    stamp = card.published_on.isoformat() if card.published_on is not None else ""
    content = hashlib.sha256(f"{card.title or ''}\n{card.url}\n{stamp}".encode()).hexdigest()
    # ``digest`` ties the row to the dedup key; ``content`` changes when the title changes.
    content_hash = hashlib.sha256(f"{digest}\n{content}".encode()).hexdigest()
    return HistoricalArtifact(
        source_id=SOURCE_METADATA,
        source_url=card.url,
        external_document_id=card.external_id,
        document_type="issuer_press_metadata",
        content_hash=content_hash,
        parser_version=PARSER_VERSION,
        fetch_status=FetchStatus.OK,
        first_observed_at=observed,
        title=card.title,
        entity_identifiers={"secid": ISSUER},
        published_at=published_at,
        published_at_precision=precision,
        historical_availability_evidence=evidence,
        historical_pit_quality=pit,
        quality_status=RecordQuality.UNRESOLVED,
        limitations=limitations,
    )


def is_blocked_listing(payload: bytes) -> bool:
    if is_antibot_shell(payload):
        return True
    lowered = payload.lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def blocked_listing_batch() -> IssuerNewsBatch:
    return IssuerNewsBatch(
        issuer=ISSUER,
        listing_url=LISTING_URL,
        artifacts=(),
        fetch_status=FetchStatus.UNSUPPORTED,
        adapter_status=AdapterStatus.BLOCKED,
        limitations=("antibot_shell", "article_body_not_fetched", "not_parsed_as_news"),
    )


def _empty_batch(limitations: tuple[str, ...]) -> IssuerNewsBatch:
    return IssuerNewsBatch(
        issuer=ISSUER,
        listing_url=LISTING_URL,
        artifacts=(),
        fetch_status=FetchStatus.EMPTY,
        adapter_status=AdapterStatus.PARTIAL,
        limitations=limitations,
    )


def _cap(limit: int) -> int:
    if limit < 1:
        return 0
    return min(limit, MAX_ITEMS)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("first_observed_at must be timezone-aware")
    return value.astimezone(UTC)


def _plain(value: str) -> str | None:
    text = re.sub(r"<[^>]+>", " ", html.unescape(value))
    text = re.sub(r"\s+", " ", text).strip(" -\u00a0")
    return text or None


def _civil_date(raw: str) -> date | None:
    match = _DMY.search(html.unescape(raw))
    if match is None:
        return None
    day, month, year = (int(match.group(index)) for index in (1, 2, 3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _slug(url: str) -> str:
    path = urlsplit(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1].strip()
    return slug
