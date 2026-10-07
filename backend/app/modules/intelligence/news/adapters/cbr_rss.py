"""CBR official RSS adapters (press / news)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.intelligence.news.adapters.base import AdapterResult, FetchedDocument
from app.modules.intelligence.news.hashing import canonical_url, content_hash, document_key
from app.modules.intelligence.news.http import NewsHttpClient
from app.modules.intelligence.news.known_at import compute_known_at
from app.modules.intelligence.news.registry import SourceDefinition
from app.modules.intelligence.news.rss import parse_feed


class CbrRssAdapter:
    def fetch(self, source: SourceDefinition, client: NewsHttpClient) -> AdapterResult:
        observed_at = datetime.now(UTC)
        payload = client.fetch_bytes(source)
        parsed = parse_feed(payload)
        warnings = list(parsed.parse_warnings)
        docs: list[FetchedDocument] = []
        for item in parsed.items[: source.max_items]:
            url = canonical_url(item.link)
            ext = item.guid
            if not url and not ext:
                warnings.append("skip_no_identity")
                continue
            body = item.summary or ""
            title = item.title
            digest = content_hash(title=title, body=body, canonical=url)
            known_at, known_basis = compute_known_at(
                policy=source.known_at_policy,
                published_at=item.published_at,
                observed_at=observed_at,
            )
            key = document_key(provider=source.provider, canonical=url, external_id=ext)
            docs.append(
                FetchedDocument(
                    document_key=key,
                    provider=source.provider,
                    source_type=source.source_type,
                    canonical_url=url,
                    title=title,
                    published_at=item.published_at,
                    observed_at=observed_at,
                    known_at=known_at,
                    content_hash=digest,
                    language=source.language,
                    raw_text=body or None,
                    external_id=ext,
                    metadata={
                        "source_id": source.source_id,
                        "adapter": source.adapter,
                        "feed_url": source.feed_url,
                        "known_at_basis": known_basis,
                        "known_at_policy": source.known_at_policy,
                        "guid": ext,
                        "feed_title": parsed.title,
                    },
                )
            )
        return AdapterResult(
            documents=tuple(docs),
            warnings=tuple(warnings),
            fetched_bytes=len(payload),
        )
