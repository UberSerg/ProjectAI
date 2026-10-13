"""Pure dedup key for issuer news metadata. No download and no article body."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.modules.intelligence.news.hashing import canonical_url

DEDUP_KEY_FIELDS = ("source", "external_id_or_canonical_url", "published_date")


@dataclass(frozen=True, slots=True)
class IssuerNewsDedupKey:
    """Identity is the external id when present, otherwise the canonical url."""

    source: str
    identity_kind: str
    identity: str
    published_on: date | None

    def as_token(self) -> str:
        stamp = self.published_on.isoformat() if self.published_on is not None else ""
        return f"{self.source}|{self.identity_kind}|{self.identity}|{stamp}"


def issuer_news_dedup_key(
    *,
    source: str,
    external_id: str | None = None,
    url: str | None = None,
    published_on: date | None = None,
) -> IssuerNewsDedupKey:
    """Build a dedup key from source, external id or canonical url, and publication date.

    ``published_on`` is a civil date. A datetime is refused so a clock cannot
    change the key. This function does not fetch anything.
    """
    src = source.strip()
    if not src or any(char in src for char in "|\n\r"):
        raise ValueError("source must be a non-empty token")
    if published_on is not None:
        if isinstance(published_on, datetime) or not isinstance(published_on, date):
            raise TypeError("published_on must be datetime.date")
    external = (external_id or "").strip()
    if external:
        if any(char in external for char in "|\n\r"):
            raise ValueError("external_id must be a single token")
        return IssuerNewsDedupKey(
            source=src,
            identity_kind="external_id",
            identity=external,
            published_on=published_on,
        )
    canonical = _canonical_news_url(url)
    if canonical is None:
        raise ValueError("issuer_news_dedup_key requires external_id or url")
    return IssuerNewsDedupKey(
        source=src,
        identity_kind="canonical_url",
        identity=canonical,
        published_on=published_on,
    )


def _canonical_news_url(url: str | None) -> str | None:
    canonical = canonical_url(url)
    if canonical is None:
        return None
    scheme, sep, rest = canonical.partition("://")
    if not sep:
        return canonical
    host, slash, path = rest.partition("/")
    if slash and path not in {"", "/"}:
        path = path.rstrip("/")
    return f"{scheme}://{host}/{path}" if slash else f"{scheme}://{host}"
