"""SQLAlchemy models for Relations Engine V1."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.market.models import Base


class RelationInput(Base):
    __tablename__ = "relation_inputs"
    __table_args__ = (
        UniqueConstraint("code", name="uq_analytics_relation_inputs_code"),
        Index(
            "ix_analytics_relation_inputs_active",
            "is_active",
            postgresql_where=text("is_active = TRUE"),
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    input_family: Mapped[str] = mapped_column(Text, nullable=False)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    feature_key: Mapped[str] = mapped_column(Text, nullable=False)
    transform: Mapped[str] = mapped_column(Text, nullable=False)
    alignment_policy: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("extra", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RelationSet(Base):
    __tablename__ = "relation_sets"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_analytics_relation_sets_code_version"),
        Index(
            "uq_analytics_relation_sets_one_active_per_code",
            "code",
            unique=True,
            postgresql_where=text("is_active = TRUE"),
        ),
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


class RelationRun(Base):
    __tablename__ = "relation_runs"
    __table_args__ = {"schema": "analytics"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    relation_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.relation_sets.id"), nullable=False
    )
    run_type: Mapped[str] = mapped_column(Text, nullable=False)
    as_of_from: Mapped[date | None] = mapped_column(Date)
    as_of_to: Mapped[date | None] = mapped_column(Date)
    cadence: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    inputs_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pairs_calculated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshots_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshots_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshots_invalid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshots_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    workflow_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RelationSnapshot(Base):
    __tablename__ = "relation_snapshots"
    __table_args__ = (
        CheckConstraint("input_a_id < input_b_id", name="ck_analytics_relation_snapshots_unordered_pair"),
        UniqueConstraint(
            "relation_set_id",
            "as_of_date",
            "window_observations",
            "input_a_id",
            "input_b_id",
            name="uq_analytics_relation_snapshots_pair",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    relation_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("analytics.relation_runs.id"), nullable=False
    )
    relation_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.relation_sets.id"), nullable=False
    )
    relation_set_version: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_observations: Mapped[int] = mapped_column(Integer, nullable=False)
    input_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.relation_inputs.id"), nullable=False
    )
    input_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.relation_inputs.id"), nullable=False
    )
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    pearson: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    spearman: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    rolling_corr_mean: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    rolling_corr_std: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    sign_consistency: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    best_leader_input_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.relation_inputs.id")
    )
    best_follower_input_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.relation_inputs.id")
    )
    best_lag: Mapped[int | None] = mapped_column(Integer)
    best_lag_pearson: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    best_lag_spearman: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RelationLagMetric(Base):
    __tablename__ = "relation_lag_metrics"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "leader_input_id",
            "follower_input_id",
            "lag",
            name="uq_analytics_relation_lag_metrics",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("analytics.relation_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    leader_input_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.relation_inputs.id"), nullable=False
    )
    follower_input_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.relation_inputs.id"), nullable=False
    )
    lag: Mapped[int] = mapped_column(Integer, nullable=False)
    pearson: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    spearman: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
