"""Orchestrate allowlisted fetch → SourceDocumentV1 persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.modules.intelligence.isolation import assert_production_isolation
from app.modules.intelligence.news.adapters import ADAPTERS
from app.modules.intelligence.news.http import NewsHttpClient, NewsHttpError
from app.modules.intelligence.news.models import IntelligenceSourceDocument
from app.modules.intelligence.news.registry import (
    SourceDefinition,
    get_source,
    list_sources,
)
from app.modules.intelligence.news.repository import persist_document, to_source_document_v1


@dataclass
class IngestResult:
    source_id: str
    ok: bool
    fetched: int = 0
    inserted: int = 0
    revised: int = 0
    duplicates: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    sample_documents: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ingest_source(
    session: Session,
    source_id: str,
    *,
    client: NewsHttpClient | None = None,
    max_sample: int = 5,
) -> IngestResult:
    assert_production_isolation()
    source = get_source(source_id)
    owns_client = client is None
    http = client or NewsHttpClient()
    try:
        return _ingest_one(session, source, http, max_sample=max_sample)
    finally:
        if owns_client:
            http.close()


def ingest_allowlisted_sources(
    session: Session,
    *,
    source_ids: list[str] | None = None,
    client: NewsHttpClient | None = None,
    max_sample: int = 3,
) -> list[IngestResult]:
    assert_production_isolation()
    owns_client = client is None
    http = client or NewsHttpClient()
    try:
        if source_ids is None:
            sources = list_sources(enabled_only=True)
        else:
            sources = [get_source(sid) for sid in source_ids]
        return [_ingest_one(session, src, http, max_sample=max_sample) for src in sources]
    finally:
        if owns_client:
            http.close()


def _ingest_one(
    session: Session,
    source: SourceDefinition,
    client: NewsHttpClient,
    *,
    max_sample: int,
) -> IngestResult:
    adapter = ADAPTERS.get(source.adapter)
    if adapter is None:
        return IngestResult(
            source_id=source.source_id,
            ok=False,
            error=f"unknown adapter: {source.adapter}",
        )
    try:
        fetched = adapter.fetch(source, client)
    except NewsHttpError as exc:
        return IngestResult(source_id=source.source_id, ok=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface adapter failures cleanly
        return IngestResult(
            source_id=source.source_id,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    result = IngestResult(
        source_id=source.source_id,
        ok=True,
        fetched=len(fetched.documents),
        warnings=list(fetched.warnings),
    )
    for doc in fetched.documents:
        outcome = persist_document(session, doc)
        result.outcomes.append(
            {
                "status": outcome.status,
                "document_id": outcome.document_id,
                "revision": outcome.revision,
                "content_hash": outcome.content_hash,
                "document_key": outcome.document_key,
            }
        )
        if outcome.status == "inserted":
            result.inserted += 1
        elif outcome.status == "revised":
            result.revised += 1
        else:
            result.duplicates += 1

        if len(result.sample_documents) < max_sample and outcome.document_id is not None:
            row = session.get(IntelligenceSourceDocument, outcome.document_id)
            if row is not None:
                result.sample_documents.append(to_source_document_v1(row).to_dict())

    return result
