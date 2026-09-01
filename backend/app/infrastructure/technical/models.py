"""SQLAlchemy models for Technical Agent V1."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.market.models import Base


class InstrumentTechnicalFeatureDaily(Base):
    __tablename__ = "instrument_technical_features_daily"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "date",
            "timeframe",
            "feature_set_id",
            name="uq_analytics_instrument_technical_features_daily",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False, default="1d")
    feature_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.feature_sets.id"), nullable=False
    )
    sma20: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    sma20_distance: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    ema20: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    ema20_distance: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    rsi14: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    atr14: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    atr14_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    has_sufficient_history: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_basic_feature_id: Mapped[int | None] = mapped_column(BigInteger)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TechnicalRun(Base):
    __tablename__ = "runs"
    __table_args__ = {"schema": "technical"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_type: Mapped[str] = mapped_column(Text, nullable=False)
    model_code: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    basic_feature_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.feature_sets.id"), nullable=False
    )
    technical_feature_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.feature_sets.id"), nullable=False
    )
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    instruments_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    technical_feature_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signal_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_watermark: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    workflow_id: Mapped[int | None] = mapped_column(BigInteger)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TechnicalSignalDaily(Base):
    __tablename__ = "signals_daily"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "as_of_date",
            "timeframe",
            "model_code",
            "model_version",
            "basic_feature_set_id",
            "technical_feature_set_id",
            name="uq_technical_signals_daily",
        ),
        {"schema": "technical"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="CASCADE"), nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False, default="1d")
    run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("technical.runs.id"))
    model_code: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    basic_feature_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.feature_sets.id"), nullable=False
    )
    technical_feature_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.feature_sets.id"), nullable=False
    )
    source_basic_feature_id: Mapped[int | None] = mapped_column(BigInteger)
    source_technical_feature_id: Mapped[int | None] = mapped_column(BigInteger)
    score: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    trend_contribution: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    momentum_contribution: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    rsi_contribution: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    volume_contribution: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
