"""Persistence models for observed fixed-income terms and cashflows."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.market.models import Base


class BondTerm(Base):
    __tablename__ = "bond_terms"
    __table_args__ = (
        UniqueConstraint("instrument_id", name="uq_investment_bond_terms_instrument"),
        {"schema": "investment"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="CASCADE"), nullable=False
    )
    bond_type: Mapped[str] = mapped_column(Text, nullable=False)
    nominal: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    currency: Mapped[str | None] = mapped_column(Text)
    coupon_type: Mapped[str | None] = mapped_column(Text)
    coupon_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    issue_date: Mapped[date | None] = mapped_column(Date)
    maturity_date: Mapped[date | None] = mapped_column(Date)
    lot_size: Mapped[int | None] = mapped_column(BigInteger)
    support_status: Mapped[str] = mapped_column(Text, nullable=False, default="RESEARCH_ONLY")
    credit_quality_status: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    known_at: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    raw_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BondCashflow(Base):
    __tablename__ = "bond_cashflows"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "cashflow_date",
            "cashflow_type",
            "source",
            name="uq_investment_bond_cashflows",
        ),
        {"schema": "investment"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="CASCADE"), nullable=False
    )
    cashflow_date: Mapped[date] = mapped_column(Date, nullable=False)
    cashflow_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    currency: Mapped[str | None] = mapped_column(Text)
    known_at: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    raw_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BondMarketSnapshot(Base):
    __tablename__ = "bond_market_snapshots"
    __table_args__ = (
        UniqueConstraint("instrument_id", "as_of", "source", name="uq_investment_bond_market_snapshot"),
        {"schema": "investment"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    clean_price_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    accrued_interest: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    yield_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    observed_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreditAgency(Base):
    __tablename__ = "credit_agencies"
    __table_args__ = (
        UniqueConstraint("code", name="uq_investment_credit_agencies_code"),
        {"schema": "investment"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(Text)
    scale_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreditRatingObservation(Base):
    """Append-only agency rating observations (ISSUER|ISSUE). Never invent rows."""

    __tablename__ = "credit_rating_observations"
    __table_args__ = {"schema": "investment"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_key: Mapped[str] = mapped_column(Text, nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="SET NULL")
    )
    issuer_id: Mapped[int | None] = mapped_column(BigInteger)
    agency_code: Mapped[str] = mapped_column(Text, nullable=False)
    rating_raw: Mapped[str | None] = mapped_column(Text)
    scale: Mapped[str | None] = mapped_column(Text)
    outlook: Mapped[str | None] = mapped_column(Text)
    action_type: Mapped[str | None] = mapped_column(Text)
    action_date: Mapped[date | None] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    known_at: Mapped[date | None] = mapped_column(Date)
    known_at_quality: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(Text)
    mapping_quality: Mapped[str] = mapped_column(Text, nullable=False, default="UNMAPPED")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="UNKNOWN")
    availability_status: Mapped[str] = mapped_column(Text, nullable=False, default="SOURCE_NOT_READY")
    raw_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreditSyncJob(Base):
    __tablename__ = "credit_sync_jobs"
    __table_args__ = (
        UniqueConstraint(
            "subject_type",
            "subject_key",
            "agency_code",
            name="uq_credit_sync_jobs_subject_agency",
        ),
        {"schema": "investment"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_key: Mapped[str] = mapped_column(Text, nullable=False)
    agency_code: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
