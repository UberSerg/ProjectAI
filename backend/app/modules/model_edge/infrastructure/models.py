"""SQLAlchemy models for Prospective Model A/B V0 and Model Diagnostics V0 (schema learning)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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


class ProspectiveModelExperiment(Base):
    """One synchronized prospective A/B experiment; only the MODEL differs between sides."""

    __tablename__ = "prospective_model_experiments"
    __table_args__ = (
        UniqueConstraint("code", name="uq_prospective_model_experiments_code"),
        {"schema": "learning"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    human_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="REGISTERED")
    candidate_a_name: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_a_version: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_a_config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_b_name: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_b_version: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_b_config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    policy_name: Mapped[str] = mapped_column(Text, nullable=False)
    risk_name: Mapped[str] = mapped_column(Text, nullable=False)
    capital: Mapped[float] = mapped_column(Float, nullable=False, default=1_000_000.0)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activation_market_watermark: Mapped[date | None] = mapped_column(Date)
    first_eligible_market_date: Mapped[date | None] = mapped_column(Date)
    shadow_portfolio_a_id: Mapped[int | None] = mapped_column(BigInteger)
    shadow_portfolio_b_id: Mapped[int | None] = mapped_column(BigInteger)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProspectiveModelComparisonBatch(Base):
    """One as_of date evaluated by both candidates on the same feature snapshot."""

    __tablename__ = "prospective_model_comparison_batches"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "as_of_date", name="uq_prospective_model_comparison_batches"
        ),
        {"schema": "learning"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("learning.prospective_model_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    market_watermark: Mapped[date | None] = mapped_column(Date)
    feature_snapshot_hash: Mapped[str | None] = mapped_column(Text)
    feature_schema_hash: Mapped[str | None] = mapped_column(Text)
    candidate_a_batch_id: Mapped[int | None] = mapped_column(BigInteger)
    candidate_b_batch_id: Mapped[int | None] = mapped_column(BigInteger)
    eligible_a: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_b: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    common_eligible: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comparability_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="NOT_COMPARABLE"
    )
    rank_correlation: Mapped[float | None] = mapped_column(Float)
    top20_overlap: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    error_message: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ModelDiagnosticsRun(Base):
    """Persisted MODEL_DIAGNOSTICS_V0 report, keyed by a deterministic input hash."""

    __tablename__ = "model_diagnostics_runs"
    __table_args__ = (
        UniqueConstraint("input_hash", name="uq_model_diagnostics_runs_input_hash"),
        {"schema": "learning"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    diagnostics_version: Mapped[str] = mapped_column(
        Text, nullable=False, default="MODEL_DIAGNOSTICS_V0"
    )
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    candidate_a_hash: Mapped[str | None] = mapped_column(Text)
    candidate_b_hash: Mapped[str | None] = mapped_column(Text)
    dataset_values_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="SUCCESS")
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
