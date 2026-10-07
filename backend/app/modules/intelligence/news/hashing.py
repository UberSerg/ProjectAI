"""Content hashing and canonical document keys."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def canonical_url(url: str | None) -> str | None:
    """Normalize URL for dedup: lowercase host, drop fragment, sort query."""
    if not url:
        return None
    raw = url.strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    # Drop common tracking params while keeping document identity.
    drop = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid"}
    query_pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in drop]
    query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


def content_hash(*, title: str | None, body: str | None, canonical: str | None) -> str:
    payload = "\n".join(
        [
            normalize_whitespace(title or ""),
            normalize_whitespace(body or ""),
            canonical or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def document_key(*, provider: str, canonical: str | None, external_id: str | None) -> str:
    if canonical:
        return f"{provider}|url|{canonical}"
    if external_id:
        return f"{provider}|id|{external_id.strip()}"
    raise ValueError("document_key requires canonical_url or external_id")
