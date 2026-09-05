"""SQLAlchemy models for Forward Signal V0 (schema learning)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.market.models import Base


class ForwardPredictionBatch(Base):
    __tablename__ = "forward_prediction_batches"
    __table_args__ = {"schema": "learning"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    segment: Mapped[str] = mapped_column(Text, nullable=False, default="FORWARD_LIVE")
    candidate_name: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_version: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    feature_schema_hash: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_values_hash: Mapped[str | None] = mapped_column(Text)
    # EXPECTED_RETURN (V0 regressor) or RANKING_SCORE (V1 ranker). A RANKING_SCORE
    # occupies predicted_return_20d but is not a return and must never be formatted as %.
    prediction_semantic: Mapped[str] = mapped_column(
        Text, nullable=False, default="EXPECTED_RETURN"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    instrument_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ineligible_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prediction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_lineage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    input_lineage_hash: Mapped[str | None] = mapped_column(Text)
    prediction_hash: Mapped[str | None] = mapped_column(Text)
    pit_status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    completeness: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    timings: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ForwardPrediction(Base):
    __tablename__ = "forward_predictions"
    __table_args__ = (
        UniqueConstraint(
            "candidate_config_hash",
            "as_of_date",
            "instrument_id",
            name="uq_forward_pred_candidate_asof_instrument",
        ),
        {"schema": "learning"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("learning.forward_prediction_batches.id", ondelete="CASCADE"), nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    instrument_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_return_20d: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer)
    eligible_count: Mapped[int | None] = mapped_column(Integer)
    percentile: Mapped[float | None] = mapped_column(Float)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False, default="OK")
    candidate_config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    feature_schema_hash: Mapped[str] = mapped_column(Text, nullable=False)
    input_lineage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    segment: Mapped[str] = mapped_column(Text, nullable=False, default="FORWARD_LIVE")
    prediction_semantic: Mapped[str] = mapped_column(
        Text, nullable=False, default="EXPECTED_RETURN"
    )
    outcome_status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING_OUTCOME")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
