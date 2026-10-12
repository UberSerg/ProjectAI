"""SQLAlchemy mapping for intelligence.source_documents."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.market.models import Base


class IntelligenceSourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("document_key", "revision", name="uq_intel_source_documents_key_rev"),
        UniqueConstraint("provider", "content_hash", name="uq_intel_source_documents_hash"),
        {"schema": "intelligence"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_key: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(Text)
    issuer_id: Mapped[int | None] = mapped_column(BigInteger)
    instrument_id: Mapped[int | None] = mapped_column(BigInteger)
    mapping_basis: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    raw_text: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExtractedFact(Base):
    """Deterministic or provider fact grounded in one source document revision."""

    __tablename__ = "extracted_facts"
    __table_args__ = {"schema": "intelligence"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("intelligence.source_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    extractor_version: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    materiality: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    direction: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    affected_horizon: Mapped[str | None] = mapped_column(Text)
    claim: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_fragment: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACCEPTED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IntelligenceEvent(Base):
    """Instrument-scoped event derived from an accepted fact. Timestamps are copies."""

    __tablename__ = "intelligence_events"
    __table_args__ = {"schema": "intelligence"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("market.instruments.id", ondelete="SET NULL"),
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    materiality: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    direction: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    title: Mapped[str | None] = mapped_column(Text)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_document_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("intelligence.source_documents.id", ondelete="SET NULL"),
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
