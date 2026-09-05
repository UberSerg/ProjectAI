"""SQLAlchemy models for External Deep History V0 staging (schema market).

These tables are staging only. Nothing here writes to market.candles.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.market.models import Base


class ExternalSource(Base):
    __tablename__ = "external_sources"
    __table_args__ = (
        UniqueConstraint("source_code", name="uq_market_external_sources_code"),
        UniqueConstraint("file_sha256", name="uq_market_external_sources_sha256"),
        {"schema": "market"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    file_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    price_semantic: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="REGISTERED")
    audit_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalSourceInstrument(Base):
    __tablename__ = "external_source_instruments"
    __table_args__ = (
        UniqueConstraint("source_id", "source_symbol", name="uq_market_external_source_instruments"),
        {"schema": "market"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.external_sources.id", ondelete="CASCADE"), nullable=False
    )
    source_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    first_date: Mapped[date | None] = mapped_column(Date)
    last_date: Mapped[date | None] = mapped_column(Date)
    observations: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    active_years: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    match_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="UNKNOWN_HISTORICAL_SYMBOL"
    )
    mapping_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    project_symbol: Mapped[str | None] = mapped_column(Text)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    research_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalCandleDaily(Base):
    """Staged external daily bar. Deliberately NOT a market.candles row."""

    __tablename__ = "external_candles_daily"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "source_symbol", "trade_date", name="uq_market_external_candles_daily"
        ),
        {"schema": "market"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.external_sources.id", ondelete="CASCADE"), nullable=False
    )
    source_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    high: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    low: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    close: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    value: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalAuditRun(Base):
    __tablename__ = "external_audit_runs"
    __table_args__ = {"schema": "market"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("market.external_sources.id", ondelete="SET NULL")
    )
    run_type: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="RUNNING")
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalReconciliation(Base):
    __tablename__ = "external_reconciliation"
    __table_args__ = (
        UniqueConstraint("source_id", "source_symbol", name="uq_market_external_reconciliation"),
        {"schema": "market"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.external_sources.id", ondelete="CASCADE"), nullable=False
    )
    source_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    project_symbol: Mapped[str | None] = mapped_column(Text)
    overlap_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    exact_ohlc_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    close_rel_med: Mapped[float | None] = mapped_column(Float)
    close_rel_p95: Mapped[float | None] = mapped_column(Float)
    close_rel_p99: Mapped[float | None] = mapped_column(Float)
    volume_rel_med: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    ca_probe_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalCuratedEligibility(Base):
    __tablename__ = "external_curated_eligibility"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "source_symbol",
            "trade_date",
            name="uq_market_external_curated_eligibility",
        ),
        {"schema": "market"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.external_sources.id", ondelete="CASCADE"), nullable=False
    )
    source_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    eligibility: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalMlReadiness(Base):
    __tablename__ = "external_ml_readiness"
    __table_args__ = (
        UniqueConstraint("source_id", "year", name="uq_market_external_ml_readiness"),
        {"schema": "market"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.external_sources.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    symbols: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    eligible_symbols: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    eligible_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    median_observations: Mapped[float | None] = mapped_column(Float)
    feature_stack_status: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    blocking_reasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
