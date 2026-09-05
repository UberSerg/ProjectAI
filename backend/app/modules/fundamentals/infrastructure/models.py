"""SQLAlchemy models for schema ``fundamentals`` (migration 20260905_0018)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.infrastructure.market.models import Base


class Issuer(Base):
    """A legal issuer. ``moex_emitent_id`` is the only identity MOEX ISS gives us."""

    __tablename__ = "issuers"
    __table_args__ = (
        UniqueConstraint("moex_emitent_id", name="uq_fundamentals_issuers_moex_emitent"),
        {"schema": "fundamentals"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    moex_emitent_id: Mapped[int | None] = mapped_column(BigInteger)
    inn: Mapped[str | None] = mapped_column(Text)
    okpo: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_en: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SecurityIssuerMapping(Base):
    """Instrument → issuer link. ``issuer_id`` stays NULL for UNMAPPED / AMBIGUOUS."""

    __tablename__ = "security_issuer_mappings"
    __table_args__ = ({"schema": "fundamentals"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="CASCADE"), nullable=False
    )
    issuer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fundamentals.issuers.id", ondelete="SET NULL")
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_secid: Mapped[str | None] = mapped_column(Text)
    isin: Mapped[str | None] = mapped_column(Text)
    mapping_status: Mapped[str] = mapped_column(Text, nullable=False, default="UNMAPPED")
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SourceDocument(Base):
    """Provenance of an ingested document. ``published_at`` is never inferred."""

    __tablename__ = "source_documents"
    __table_args__ = ({"schema": "fundamentals"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    provider_document_id: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(Text)
    storage_ref: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MetricRegistryEntry(Base):
    """Normalised metric vocabulary. ``applies_to_banks`` is conservative by design."""

    __tablename__ = "metric_registry"
    __table_args__ = ({"schema": "fundamentals"},)

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    title_ru: Mapped[str] = mapped_column(Text, nullable=False)
    title_en: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    applies_to_banks: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="SUPPORTED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FinancialReport(Base):
    """One disclosed report version. ``known_at`` is availability, ``period_end`` economics."""

    __tablename__ = "financial_reports"
    __table_args__ = (
        UniqueConstraint(
            "issuer_id",
            "reporting_standard",
            "period_type",
            "period_end",
            "report_version",
            "source",
            name="uq_fundamentals_financial_reports",
        ),
        {"schema": "fundamentals"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    issuer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fundamentals.issuers.id", ondelete="CASCADE"), nullable=False
    )
    reporting_standard: Mapped[str] = mapped_column(Text, nullable=False)
    period_type: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    known_at: Mapped[date] = mapped_column(Date, nullable=False)
    known_at_precision: Mapped[str] = mapped_column(Text, nullable=False, default="DATE")
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fundamentals.source_documents.id", ondelete="SET NULL")
    )
    report_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_restatement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    currency: Mapped[str | None] = mapped_column(Text)
    unit_scale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FinancialFact(Base):
    """One metric value inside a report version."""

    __tablename__ = "financial_facts"
    __table_args__ = (
        UniqueConstraint(
            "report_id",
            "metric_code",
            "source_metric_name",
            name="uq_fundamentals_financial_facts",
        ),
        {"schema": "fundamentals"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("fundamentals.financial_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_code: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(Text)
    unit_scale: Mapped[str | None] = mapped_column(Text)
    source_metric_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalization_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="SOURCE_ONLY"
    )
    quality_status: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DividendEvent(Base):
    """One dividend disclosure version. Superseded versions are kept, never rewritten."""

    __tablename__ = "dividend_events"
    __table_args__ = ({"schema": "fundamentals"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    issuer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fundamentals.issuers.id", ondelete="CASCADE")
    )
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="CASCADE")
    )
    announcement_date: Mapped[date | None] = mapped_column(Date)
    known_at: Mapped[date] = mapped_column(Date, nullable=False)
    board_recommendation_date: Mapped[date | None] = mapped_column(Date)
    shareholder_approval_date: Mapped[date | None] = mapped_column(Date)
    record_date: Mapped[date | None] = mapped_column(Date)
    ex_date: Mapped[date | None] = mapped_column(Date)
    payment_date: Mapped[date | None] = mapped_column(Date)
    amount_per_share: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fundamentals.source_documents.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fundamentals.dividend_events.id", ondelete="SET NULL")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CorporateEvent(Base):
    """Structured corporate event with a mandatory availability date."""

    __tablename__ = "corporate_events"
    __table_args__ = ({"schema": "fundamentals"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    issuer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fundamentals.issuers.id", ondelete="SET NULL")
    )
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    known_at: Mapped[date] = mapped_column(Date, nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IngestionRun(Base):
    """Audit trail of every attempted ingestion, including DEFERRED / FAILED ones."""

    __tablename__ = "ingestion_runs"
    __table_args__ = ({"schema": "fundamentals"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_range: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="RUNNING")
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


def fundamentals_schema_ready(session: Session) -> bool:
    """True when migration 20260905_0018 has been applied to this database."""
    return bool(
        session.execute(
            text("SELECT to_regclass('fundamentals.issuers') IS NOT NULL")
        ).scalar_one()
    )
