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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BondMarketSnapshot(Base):
    __tablename__ = "bond_market_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "as_of", "source", name="uq_investment_bond_market_snapshot"
        ),
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
