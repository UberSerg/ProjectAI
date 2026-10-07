"""Adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.modules.intelligence.news.http import NewsHttpClient
from app.modules.intelligence.news.registry import SourceDefinition


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    """Pre-persist draft mapped to SourceDocumentV1 fields."""

    document_key: str
    provider: str
    source_type: str
    canonical_url: str | None
    title: str | None
    published_at: datetime | None
    observed_at: datetime
    known_at: datetime
    content_hash: str
    language: str | None
    raw_text: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    external_id: str | None = None


@dataclass(frozen=True, slots=True)
class AdapterResult:
    documents: tuple[FetchedDocument, ...]
    warnings: tuple[str, ...] = ()
    fetched_bytes: int = 0


class NewsAdapter(Protocol):
    def fetch(self, source: SourceDefinition, client: NewsHttpClient) -> AdapterResult: ...
