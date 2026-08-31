"""SQLAlchemy models for analytics feature store."""

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


class FeatureSet(Base):
    __tablename__ = "feature_sets"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_analytics_feature_sets_code_version"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeatureRun(Base):
    __tablename__ = "feature_runs"
    __table_args__ = {"schema": "analytics"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    feature_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.feature_sets.id"), nullable=False
    )
    run_type: Mapped[str] = mapped_column(Text, nullable=False)
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    instruments_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    instrument_rows_calculated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    series_rows_calculated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_invalid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    workflow_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InstrumentFeatureDaily(Base):
    __tablename__ = "instrument_features_daily"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "date",
            "timeframe",
            "feature_set_id",
            name="uq_analytics_instrument_features_daily",
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
    feature_version: Mapped[int] = mapped_column(Integer, nullable=False)
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    return_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    return_2d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    return_3d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    return_5d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    return_10d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    return_20d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    log_return_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    volatility_5d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    volatility_20d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    drawdown_20d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    volume_change_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    volume_zscore_20d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    has_sufficient_history: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SeriesFeatureDaily(Base):
    __tablename__ = "series_features_daily"
    __table_args__ = (
        UniqueConstraint("series_id", "date", "feature_set_id", name="uq_analytics_series_features_daily"),
        {"schema": "analytics"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    series_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.series.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    feature_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.feature_sets.id"), nullable=False
    )
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    previous_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    absolute_change: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    pct_change: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    days_since_change: Mapped[int | None] = mapped_column(Integer)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
