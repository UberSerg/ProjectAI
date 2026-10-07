"""SQLAlchemy models for intelligence.knowledge_rules (+ evaluations)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.market.models import Base


class KnowledgeRuleRow(Base):
    __tablename__ = "knowledge_rules"
    __table_args__ = (
        UniqueConstraint("rule_id", "version", name="uq_intel_knowledge_rules"),
        {"schema": "intelligence"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    principle: Mapped[str] = mapped_column(Text, nullable=False)
    applicability: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    required_evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    contraindications: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    severity: Mapped[str] = mapped_column(Text, nullable=False, default="MEDIUM")
    source_reference: Mapped[str | None] = mapped_column(Text)
    source_location: Mapped[str | None] = mapped_column(Text)
    created_from: Mapped[str] = mapped_column(Text, nullable=False, default="kraken_methodology")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeRuleEvaluationRow(Base):
    __tablename__ = "knowledge_rule_evaluations"
    __table_args__ = {"schema": "intelligence"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="CASCADE")
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
