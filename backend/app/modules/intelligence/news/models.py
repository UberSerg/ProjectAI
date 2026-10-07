"""SQLAlchemy mapping for intelligence.source_documents."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, Text, UniqueConstraint, func
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
