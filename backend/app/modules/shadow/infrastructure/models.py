"""SQLAlchemy models for Shadow Portfolio V0 (schema portfolio)."""

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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.market.models import Base


class ShadowPortfolioSpec(Base):
    __tablename__ = "shadow_portfolio_specs"
    __table_args__ = (
        UniqueConstraint("config_hash", name="uq_shadow_portfolio_specs_config_hash"),
        UniqueConstraint("name", name="uq_shadow_portfolio_specs_name"),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    experiment_group: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False, default="v0")
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_name: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_version: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_values_hash: Mapped[str | None] = mapped_column(Text)
    policy_name: Mapped[str] = mapped_column(Text, nullable=False)
    risk_name: Mapped[str] = mapped_column(Text, nullable=False)
    entry_quantile: Mapped[float] = mapped_column(Float, nullable=False, default=0.20)
    exit_quantile: Mapped[float] = mapped_column(Float, nullable=False, default=0.35)
    min_trade_weight_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.02)
    max_single_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.20)
    dd_trigger: Mapped[float | None] = mapped_column(Float)
    dd_recovery: Mapped[float | None] = mapped_column(Float)
    dd_risk_off_gross: Mapped[float | None] = mapped_column(Float)
    dd_normal_gross: Mapped[float | None] = mapped_column(Float)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False, default=1_000_000.0)
    commission_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slippage_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fractional_shares: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dividend_cash: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShadowPortfolio(Base):
    __tablename__ = "shadow_portfolios"
    __table_args__ = (
        UniqueConstraint("spec_id", name="uq_shadow_portfolios_spec"),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    spec_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("portfolio.shadow_portfolio_specs.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="INITIALIZED")
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_forward_batch_id: Mapped[int | None] = mapped_column(BigInteger)
    first_forward_as_of_date: Mapped[date | None] = mapped_column(Date)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    peak_nav: Mapped[float] = mapped_column(Float, nullable=False)
    exposure_cap: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    risk_mode: Mapped[str] = mapped_column(Text, nullable=False, default="normal")
    last_processed_market_date: Mapped[date | None] = mapped_column(Date)
    last_processed_prediction_batch_id: Mapped[int | None] = mapped_column(BigInteger)
    last_decision_iso_week: Mapped[str | None] = mapped_column(Text)
    last_decision_id: Mapped[int | None] = mapped_column(BigInteger)
    positions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShadowDecision(Base):
    __tablename__ = "shadow_decisions"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "iso_week", name="uq_shadow_decisions_portfolio_week"),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.shadow_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    forward_batch_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    signal_as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    signal_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    iso_week: Mapped[str] = mapped_column(Text, nullable=False)
    policy_name: Mapped[str] = mapped_column(Text, nullable=False)
    risk_name: Mapped[str] = mapped_column(Text, nullable=False)
    risk_mode: Mapped[str] = mapped_column(Text, nullable=False)
    exposure_cap: Mapped[float] = mapped_column(Float, nullable=False)
    targets: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShadowOrder(Base):
    __tablename__ = "shadow_orders"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.shadow_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    decision_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.shadow_decisions.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    target_weight: Mapped[float] = mapped_column(Float, nullable=False)
    target_notional: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    predicted_return_20d: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    eligible_count: Mapped[int | None] = mapped_column(Integer)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    min_execution_date: Mapped[date] = mapped_column(Date, nullable=False)
    execution_date: Mapped[date | None] = mapped_column(Date)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShadowFill(Base):
    __tablename__ = "shadow_fills"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_shadow_fills_order"),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.shadow_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.shadow_orders.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    raw_open: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price: Mapped[float] = mapped_column(Float, nullable=False)
    notional: Mapped[float] = mapped_column(Float, nullable=False)
    commission: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slippage_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    execution_date: Mapped[date] = mapped_column(Date, nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShadowNavDaily(Base):
    __tablename__ = "shadow_nav_daily"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "as_of_date", name="uq_shadow_nav_daily"),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.shadow_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    market_value: Mapped[float] = mapped_column(Float, nullable=False)
    nav: Mapped[float] = mapped_column(Float, nullable=False)
    gross_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    peak_nav: Mapped[float] = mapped_column(Float, nullable=False)
    position_count: Mapped[int] = mapped_column(Integer, nullable=False)
    benchmark_value: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShadowRiskEvent(Base):
    __tablename__ = "shadow_risk_events"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.shadow_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    nav: Mapped[float] = mapped_column(Float, nullable=False)
    running_peak: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    previous_mode: Mapped[str] = mapped_column(Text, nullable=False)
    new_mode: Mapped[str] = mapped_column(Text, nullable=False)
    previous_exposure_cap: Mapped[float] = mapped_column(Float, nullable=False)
    new_exposure_cap: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
