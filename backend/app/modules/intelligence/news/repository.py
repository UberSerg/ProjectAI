"""Idempotent persistence into intelligence.source_documents."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.snapshots_domain import SourceDocumentV1
from app.modules.intelligence.news.adapters.base import FetchedDocument
from app.modules.intelligence.news.models import IntelligenceSourceDocument


@dataclass(frozen=True, slots=True)
class PersistOutcome:
    status: str  # inserted | duplicate_hash | duplicate_unchanged | revised
    document_id: int | None
    revision: int | None
    content_hash: str
    document_key: str


def persist_document(session: Session, doc: FetchedDocument) -> PersistOutcome:
    """Insert with content-hash + document_key dedup and revision support.

    - Same (provider, content_hash) → skip (idempotent).
    - Same document_key with identical latest hash → skip.
    - Same document_key with new hash → insert next revision.
    """
    existing_hash = session.scalar(
        select(IntelligenceSourceDocument).where(
            IntelligenceSourceDocument.provider == doc.provider,
            IntelligenceSourceDocument.content_hash == doc.content_hash,
        )
    )
    if existing_hash is not None:
        return PersistOutcome(
            status="duplicate_hash",
            document_id=existing_hash.id,
            revision=existing_hash.revision,
            content_hash=doc.content_hash,
            document_key=doc.document_key,
        )

    latest = session.scalar(
        select(IntelligenceSourceDocument)
        .where(IntelligenceSourceDocument.document_key == doc.document_key)
        .order_by(IntelligenceSourceDocument.revision.desc())
        .limit(1)
    )
    if latest is not None and latest.content_hash == doc.content_hash:
        return PersistOutcome(
            status="duplicate_unchanged",
            document_id=latest.id,
            revision=latest.revision,
            content_hash=doc.content_hash,
            document_key=doc.document_key,
        )

    revision = 1 if latest is None else latest.revision + 1
    status = "inserted" if latest is None else "revised"

    row = IntelligenceSourceDocument(
        document_key=doc.document_key,
        provider=doc.provider,
        source_type=doc.source_type,
        canonical_url=doc.canonical_url,
        title=doc.title,
        published_at=doc.published_at,
        observed_at=doc.observed_at,
        known_at=doc.known_at,
        content_hash=doc.content_hash,
        language=doc.language,
        parse_status="RAW",
        raw_text=doc.raw_text,
        metadata_=dict(doc.metadata),
        revision=revision,
    )
    session.add(row)
    session.flush()
    return PersistOutcome(
        status=status,
        document_id=row.id,
        revision=revision,
        content_hash=doc.content_hash,
        document_key=doc.document_key,
    )


def to_source_document_v1(row: IntelligenceSourceDocument) -> SourceDocumentV1:
    return SourceDocumentV1(
        id=str(row.id),
        provider=row.provider,
        source_type=row.source_type,
        canonical_url=row.canonical_url,
        title=row.title,
        published_at=row.published_at,
        observed_at=row.observed_at,
        known_at=row.known_at,
        content_hash=row.content_hash,
        language=row.language,
        issuer_id=row.issuer_id,
        instrument_id=row.instrument_id,
        mapping_basis=row.mapping_basis,
        parse_status=row.parse_status,
        raw_text=row.raw_text,
        metadata={
            **(row.metadata_ or {}),
            "revision": row.revision,
            "document_key": row.document_key,
            "ingested_at": row.ingested_at.isoformat() if row.ingested_at else None,
        },
    )
