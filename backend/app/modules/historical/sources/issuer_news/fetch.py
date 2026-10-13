"""Fetch Lukoil listing pages only. Release URLs are refused.

Two pages of 10 cards fill the metadata cap of 20. The response HTML may
contain teasers; callers must parse with ``parse_lukoil_press_pages``, which
drops them. This module does not request article bodies.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

from app.modules.historical.domain.evidence import AdapterStatus, FetchStatus
from app.modules.historical.sources.issuer_news.listing import (
    ISSUER,
    LISTING_URL,
    MAX_ITEMS,
    IssuerNewsBatch,
    blocked_listing_batch,
    is_blocked_listing,
    parse_lukoil_press_pages,
)

PAGE_SIZE = 10
MAX_PAGES = 2
USER_AGENT = "ProjectAI-HistoricalIssuerNews/1.0 (+research; metadata-only; no-article-body)"
_MAX_BYTES = 2_000_000

Transport = Callable[[str], tuple[int, bytes]]


@dataclass(frozen=True, slots=True)
class ListingPageFetch:
    url: str
    http_status: int
    new_items: int


@dataclass(frozen=True, slots=True)
class IssuerNewsProbe:
    issuer: str
    url: str
    http_status: int
    pages: tuple[ListingPageFetch, ...]
    batch: IssuerNewsBatch


class ListingFetchError(RuntimeError):
    """The listing host could not be read. Article URLs are not a fallback."""


def lukoil_listing_url(*, skip: int, take: int = PAGE_SIZE) -> str:
    assert_listing_url(f"{LISTING_URL}?skip={skip}&take={take}")
    return f"{LISTING_URL}?skip={skip}&take={take}"


def assert_listing_url(url: str) -> None:
    """Allow only the two pilot listing pages. A release path is an article."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or parts.netloc != "lukoil.ru":
        raise ValueError("host_not_allowlisted")
    if parts.fragment or parts.path != "/PressCenter/Pressreleases":
        raise ValueError("article_fetch_refused")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if set(query) - {"skip", "take"}:
        raise ValueError("unexpected_query")
    try:
        skip = int(query["skip"])
        take = int(query["take"])
    except (KeyError, ValueError) as exc:
        raise ValueError("listing_query_incomplete") from exc
    allowed_skip = {index * PAGE_SIZE for index in range(MAX_PAGES)}
    if skip not in allowed_skip or take != PAGE_SIZE:
        raise ValueError("page_outside_metadata_cap")


def fetch_lukoil_press_metadata(
    *,
    first_observed_at: datetime,
    limit: int = MAX_ITEMS,
    transport: Transport | None = None,
) -> IssuerNewsProbe:
    """GET listing pages until the cap or the page size runs out."""
    reader = transport or _urllib_transport
    cap = MAX_ITEMS if limit > MAX_ITEMS else limit
    pages: list[ListingPageFetch] = []
    payloads: list[bytes] = []
    seen = 0
    blocked = False
    http_status = 0
    for index in range(MAX_PAGES):
        if seen >= cap:
            break
        url = lukoil_listing_url(skip=index * PAGE_SIZE)
        status, body = reader(url)
        if index == 0:
            http_status = status
        if status == 403 or is_blocked_listing(body):
            blocked = True
            pages.append(ListingPageFetch(url=url, http_status=status, new_items=0))
            break
        if status != 200:
            pages.append(ListingPageFetch(url=url, http_status=status, new_items=0))
            break
        before = seen
        page_batch = parse_lukoil_press_pages((body,), first_observed_at=first_observed_at, limit=cap)
        fresh = len(page_batch.artifacts)
        # Re-parse the accumulated pages so cross-page URL duplicates collapse once.
        payloads.append(body)
        merged = parse_lukoil_press_pages(payloads, first_observed_at=first_observed_at, limit=cap)
        seen = len(merged.artifacts)
        pages.append(ListingPageFetch(url=url, http_status=status, new_items=seen - before))
        if fresh == 0 or seen == before:
            break
    if blocked and not payloads:
        batch = blocked_listing_batch()
    elif not payloads:
        limitations = ("metadata_only", "article_body_not_fetched", f"http_{http_status}")
        batch = _failed_batch(http_status, limitations)
    else:
        batch = parse_lukoil_press_pages(payloads, first_observed_at=first_observed_at, limit=cap)
        extra: list[str] = []
        if blocked:
            extra.append("later_page_blocked")
        if any(page.http_status != 200 for page in pages):
            extra.append("listing_page_not_ok")
        if extra:
            batch = replace(batch, limitations=batch.limitations + tuple(extra))
    if http_status == 0 and pages:
        http_status = pages[0].http_status
    return IssuerNewsProbe(
        issuer=ISSUER,
        url=LISTING_URL,
        http_status=http_status,
        pages=tuple(pages),
        batch=batch,
    )


def _failed_batch(status: int, limitations: tuple[str, ...]) -> IssuerNewsBatch:
    fetch_status = FetchStatus.FORBIDDEN if status in {401, 403} else FetchStatus.FAILED
    adapter = AdapterStatus.BLOCKED if status in {401, 403} else AdapterStatus.FAILED
    return IssuerNewsBatch(
        issuer=ISSUER,
        listing_url=LISTING_URL,
        artifacts=(),
        fetch_status=fetch_status,
        adapter_status=adapter,
        limitations=limitations,
    )


def _urllib_transport(url: str) -> tuple[int, bytes]:
    assert_listing_url(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return int(response.status), response.read(_MAX_BYTES)
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(_MAX_BYTES)
    except urllib.error.URLError as exc:
        raise ListingFetchError(str(exc.reason)) from exc
