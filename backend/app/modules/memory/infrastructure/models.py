"""Personal Decision Memory V1 ORM (schema ``memory``, Memory DB only).

No SQL foreign keys to Core tables: ``portfolio_id``, ``instrument_id`` and
``personal_operation_id`` are soft references validated in the application layer.
"""

from __future__ import annotations

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.memory.infrastructure.base import MemoryBase


class PersonalDecisionRecord(MemoryBase):
    __tablename__ = "personal_decision_records"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "idempotency_key",
            name="uq_personal_decision_records_idempotency",
        ),
        {"schema": "memory"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    portfolio_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_as_of: Mapped[date | None] = mapped_column(Date)
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    new_cash_rub: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    decision_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    canonical_hash: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    broker_fee_provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    actions: Mapped[list[PersonalDecisionAction]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
        order_by="PersonalDecisionAction.id",
    )


class PersonalDecisionAction(MemoryBase):
    __tablename__ = "personal_decision_actions"
    __table_args__ = {"schema": "memory"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    decision_record_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("memory.personal_decision_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_action_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str | None] = mapped_column(Text)
    instrument_id: Mapped[int | None] = mapped_column(BigInteger)
    reason_codes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    target_weight: Mapped[Decimal | None] = mapped_column(Numeric)
    current_weight: Mapped[Decimal | None] = mapped_column(Numeric)
    lots_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    units_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    estimated_notional: Mapped[Decimal | None] = mapped_column(Numeric)
    limitations: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    action_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    baseline_price: Mapped[Decimal | None] = mapped_column(Numeric)
    baseline_market_date: Mapped[date | None] = mapped_column(Date)
    baseline_price_source: Mapped[str | None] = mapped_column(Text)
    baseline_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    baseline_status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    record: Mapped[PersonalDecisionRecord] = relationship(back_populates="actions")
    outcomes: Mapped[list[PersonalDecisionOutcome]] = relationship(
        back_populates="action",
        cascade="all, delete-orphan",
        order_by="PersonalDecisionOutcome.horizon_sessions",
    )
    links: Mapped[list[PersonalDecisionOperationLink]] = relationship(
        back_populates="action",
        cascade="all, delete-orphan",
        order_by="PersonalDecisionOperationLink.id",
    )


class PersonalDecisionOperationLink(MemoryBase):
    """Advisory user-confirmed link; ``personal_operation_id`` is a soft Core reference."""

    __tablename__ = "personal_decision_operation_links"
    __table_args__ = {"schema": "memory"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    decision_action_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("memory.personal_decision_actions.id", ondelete="CASCADE"),
        nullable=False,
    )
    portfolio_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    personal_operation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    link_source: Mapped[str] = mapped_column(Text, nullable=False, default="USER_CONFIRMED")
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    action: Mapped[PersonalDecisionAction] = relationship(back_populates="links")


class PersonalDecisionOutcome(MemoryBase):
    __tablename__ = "personal_decision_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "decision_action_id",
            "horizon_sessions",
            name="uq_personal_decision_outcomes_action_horizon",
        ),
        {"schema": "memory"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    decision_action_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("memory.personal_decision_actions.id", ondelete="CASCADE"),
        nullable=False,
    )
    horizon_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    target_session_date: Mapped[date | None] = mapped_column(Date)
    observed_session_date: Mapped[date | None] = mapped_column(Date)
    baseline_price: Mapped[Decimal | None] = mapped_column(Numeric)
    observed_price: Mapped[Decimal | None] = mapped_column(Numeric)
    return_type: Mapped[str] = mapped_column(Text, nullable=False, default="PRICE_RETURN")
    forward_return: Mapped[Decimal | None] = mapped_column(Numeric)
    directional_alignment: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    action: Mapped[PersonalDecisionAction] = relationship(back_populates="outcomes")
