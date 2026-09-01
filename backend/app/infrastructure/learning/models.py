"""SQLAlchemy models for Dataset / PIT Join V0."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.market.models import Base


class DatasetSpec(Base):
    __tablename__ = "dataset_specs"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_learning_dataset_specs_code_version"),
        {"schema": "learning"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    feature_manifest: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    relation_contexts: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    label_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    quality_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    basic_feature_set_code: Mapped[str] = mapped_column(Text, nullable=False)
    basic_feature_set_version: Mapped[int] = mapped_column(Integer, nullable=False)
    technical_feature_set_code: Mapped[str] = mapped_column(Text, nullable=False)
    technical_feature_set_version: Mapped[int] = mapped_column(Integer, nullable=False)
    technical_model_code: Mapped[str] = mapped_column(Text, nullable=False)
    technical_model_version: Mapped[int] = mapped_column(Integer, nullable=False)
    technical_model_config_hash: Mapped[str | None] = mapped_column(Text)
    relation_set_code: Mapped[str] = mapped_column(Text, nullable=False)
    relation_set_version: Mapped[int] = mapped_column(Integer, nullable=False)
    universe_policy: Mapped[str] = mapped_column(Text, nullable=False, default="current_active_instruments")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetRun(Base):
    __tablename__ = "dataset_runs"
    __table_args__ = {"schema": "learning"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_spec_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning.dataset_specs.id"), nullable=False
    )
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    instruments_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    samples_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_1d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_5d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_10d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_20d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    core_invalid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    technical_missing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relation_missing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_labels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pit_violations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pit_status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    source_watermark: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    coverage_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resolved_universe: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    dataset_hash: Mapped[str | None] = mapped_column(Text)
    workflow_id: Mapped[int | None] = mapped_column(BigInteger)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetSampleDaily(Base):
    __tablename__ = "dataset_samples_daily"
    __table_args__ = (
        UniqueConstraint(
            "dataset_run_id",
            "instrument_id",
            "as_of_date",
            name="uq_learning_dataset_samples_daily",
        ),
        {"schema": "learning"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("learning.dataset_runs.id", ondelete="CASCADE"), nullable=False
    )
    dataset_spec_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning.dataset_specs.id"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="CASCADE"), nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    feature_quality: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    label_quality: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    training_eligibility: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    lineage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
