"""SQLAlchemy models for Forward Outcome Evaluator V0."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.market.models import Base


class ForwardPredictionOutcome(Base):
    __tablename__ = "forward_prediction_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "forward_prediction_id",
            "horizon_observations",
            "evaluator_version",
            name="uq_forward_outcome_pred_horizon_version",
        ),
        {"schema": "learning"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    forward_prediction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("learning.forward_predictions.id", ondelete="CASCADE"), nullable=False
    )
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("learning.forward_prediction_batches.id", ondelete="CASCADE"), nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    instrument_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    horizon_observations: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    evaluator_version: Mapped[str] = mapped_column(Text, nullable=False, default="forward_outcome_v0")
    target_date: Mapped[date | None] = mapped_column(Date)
    predicted_return_20d: Mapped[float] = mapped_column(Float, nullable=False)
    realized_return_20d: Mapped[float | None] = mapped_column(Float)
    prediction_error: Mapped[float | None] = mapped_column(Float)
    absolute_error: Mapped[float | None] = mapped_column(Float)
    direction_correct: Mapped[bool | None] = mapped_column(Boolean)
    mechanical_ca_normalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING_OUTCOME")
    label_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ForwardBatchEvaluation(Base):
    __tablename__ = "forward_batch_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "horizon_observations",
            "evaluator_version",
            name="uq_forward_batch_eval_version",
        ),
        {"schema": "learning"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("learning.forward_prediction_batches.id", ondelete="CASCADE"), nullable=False
    )
    evaluator_version: Mapped[str] = mapped_column(Text, nullable=False, default="forward_outcome_v0")
    horizon_observations: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evaluated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mean_predicted: Mapped[float | None] = mapped_column(Float)
    mean_realized: Mapped[float | None] = mapped_column(Float)
    mae: Mapped[float | None] = mapped_column(Float)
    rmse: Mapped[float | None] = mapped_column(Float)
    directional_accuracy: Mapped[float | None] = mapped_column(Float)
    spearman_rank_ic: Mapped[float | None] = mapped_column(Float)
    top20_realized_mean: Mapped[float | None] = mapped_column(Float)
    bottom20_realized_mean: Mapped[float | None] = mapped_column(Float)
    top_minus_bottom_spread: Mapped[float | None] = mapped_column(Float)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
