"""Manual / Personal Portfolio persistence (schema portfolio)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.market.models import Base


class FeeProfile(Base):
    """Versioned broker tariff profile (builtin Sber is read_only)."""

    __tablename__ = "fee_profiles"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_fee_profiles_code_version"),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    broker_code: Mapped[str] = mapped_column(Text, nullable=False)
    broker_name: Mapped[str] = mapped_column(Text, nullable=False)
    tariff_name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_note: Mapped[str | None] = mapped_column(Text)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rules: Mapped[list[FeeRule]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    broker_accounts: Mapped[list[BrokerAccount]] = relationship(back_populates="fee_profile")


class FeeRule(Base):
    """Match dimensions + percentage/fixed fee; priority + validity window."""

    __tablename__ = "fee_rules"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fee_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.fee_profiles.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str | None] = mapped_column(Text)
    market: Mapped[str | None] = mapped_column(Text)
    trading_system: Mapped[str | None] = mapped_column(Text)
    execution_channel: Mapped[str | None] = mapped_column(Text)
    side: Mapped[str | None] = mapped_column(Text)
    asset_class: Mapped[str | None] = mapped_column(Text)
    instrument_subtype: Mapped[str | None] = mapped_column(Text)
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="SET NULL")
    )
    instrument_symbol: Mapped[str | None] = mapped_column(Text)
    turnover_from: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    turnover_to: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    fee_type: Mapped[str] = mapped_column(Text, nullable=False, default="PERCENTAGE")
    percentage_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    fixed_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    exclude_from_turnover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    explanation: Mapped[str | None] = mapped_column(Text)
    source_note: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped[FeeProfile] = relationship(back_populates="rules")


class BrokerAccount(Base):
    """User broker book linked to a FeeProfile. No credentials stored."""

    __tablename__ = "broker_accounts"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    broker_code: Mapped[str] = mapped_column(Text, nullable=False)
    broker_name: Mapped[str] = mapped_column(Text, nullable=False)
    tariff_name: Mapped[str | None] = mapped_column(Text)
    fee_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.fee_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    base_currency: Mapped[str] = mapped_column(Text, nullable=False, default="RUB")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    fee_profile: Mapped[FeeProfile] = relationship(back_populates="broker_accounts")
    portfolios: Mapped[list[ManualPortfolio]] = relationship(back_populates="broker_account")


class ManualPortfolio(Base):
    __tablename__ = "manual_portfolios"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="MANUAL")
    base_currency: Mapped[str] = mapped_column(Text, nullable=False, default="RUB")
    cash_rub: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="DRAFT")
    note: Mapped[str | None] = mapped_column(Text)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_contributed_rub: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0")
    )
    total_withdrawn_rub: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0")
    )
    realized_pnl_rub: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0")
    )
    broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("portfolio.broker_accounts.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    broker_account: Mapped[BrokerAccount | None] = relationship(back_populates="portfolios")
    positions: Mapped[list[ManualPosition]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )
    operations: Mapped[list[PersonalOperation]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
        order_by="PersonalOperation.occurred_at.asc(), PersonalOperation.id.asc()",
    )


class ManualPosition(Base):
    __tablename__ = "manual_positions"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "instrument_id",
            name="uq_portfolio_manual_positions_portfolio_instrument",
        ),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.manual_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="RESTRICT"), nullable=False
    )
    units: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    average_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    note: Mapped[str | None] = mapped_column(Text)
    non_standard_lot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    portfolio: Mapped[ManualPortfolio] = relationship(back_populates="positions")


class PersonalOperation(Base):
    """Append-only personal portfolio journal (corrections via SUPERSEDED + replacement)."""

    __tablename__ = "personal_operations"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "idempotency_key",
            name="uq_personal_operations_idempotency",
        ),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.manual_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    operation_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="RESTRICT")
    )
    lots: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    units: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    commission: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="RUB")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="MANUAL")
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    supersedes_operation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("portfolio.personal_operations.id", ondelete="SET NULL")
    )
    correction_reason: Mapped[str | None] = mapped_column(Text)
    broker_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("portfolio.broker_accounts.id", ondelete="SET NULL")
    )
    fee_rule_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("portfolio.fee_rules.id", ondelete="SET NULL")
    )
    commission_source: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    portfolio: Mapped[ManualPortfolio] = relationship(back_populates="operations")
