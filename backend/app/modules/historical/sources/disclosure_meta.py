"""DISC-03 disclosure metadata identity. Pure functions, no network.

Discover stays blocked. A single direct GET of the public RSS candidate
``https://www.e-disclosure.ru/portal/rss.aspx`` on 2026-10-13 returned the
e-disclosure Forbidden challenge (HTTP 403). That page is not a metadata feed.
This module does not fetch, does not solve the challenge, and does not mint an
id for the shell.

Dedup rule: two records are duplicates when both have the same canonical URL.
Canonical form is ``intelligence.news.hashing.canonical_url``: lowercase host,
drop the fragment, sort the query, drop ``utm_*`` and ``fbclid``. Scheme,
``www``, and trailing-slash differences stay distinct. Title, ``published_at``,
and external id do not merge records. The first record for a canonical URL is
kept. An anti-bot HTML shell is not a filing and returns no record, so it
receives no id.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.modules.historical.sources.disclosure.classify import is_antibot_shell
from app.modules.intelligence.news.hashing import canonical_url

DISCOVER_STATUS = "BLOCKED"
DEDUP_DESIGN_STATUS = "READY"
METADATA_PROBE_URL = "https://www.e-disclosure.ru/portal/rss.aspx"


@dataclass(frozen=True, slots=True)
class DisclosureMeta:
    title: str | None
    url: str | None
    canonical_url: str | None
    published_at: datetime | None
    external_id: str | None

    @property
    def dedup_key(self) -> str | None:
        return self.canonical_url


def disclosure_meta(
    *,
    title: str | None,
    url: str | None,
    published_at: datetime | None,
    external_id: str | None,
    body: bytes | None = None,
) -> DisclosureMeta | None:
    """Build a metadata identity from title, url, published_at, and external id.

    ``body`` is only a gate. When it is the anti-bot HTML shell the function
    returns None and drops every supplied field, including ``external_id``.
    The body is never parsed into a title, date, or filing.
    """
    if body is not None and is_antibot_shell(body):
        return None
    return DisclosureMeta(
        title=_text(title),
        url=_text(url),
        canonical_url=canonical_url(url),
        published_at=published_at,
        external_id=_text(external_id),
    )


def shares_canonical_url(left: DisclosureMeta, right: DisclosureMeta) -> bool:
    """True when both identities share one non-empty canonical URL."""
    if left.canonical_url is None or right.canonical_url is None:
        return False
    return left.canonical_url == right.canonical_url


def dedupe_disclosure_metadata(items: Sequence[DisclosureMeta]) -> tuple[DisclosureMeta, ...]:
    """Keep the first record for each canonical URL, preserving input order.

    Records with no canonical URL stay in place and are not collapsed by title,
    publication time, or external id.
    """
    seen: set[str] = set()
    kept: list[DisclosureMeta] = []
    for item in items:
        key = item.canonical_url
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        kept.append(item)
    return tuple(kept)


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped
