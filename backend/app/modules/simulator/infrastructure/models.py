"""SQLAlchemy models for Historical Simulator V0 (schema portfolio)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.market.models import Base


class SimulationSpec(Base):
    __tablename__ = "simulation_specs"
    __table_args__ = (
        UniqueConstraint("config_hash", name="uq_portfolio_simulation_specs_config_hash"),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    segment: Mapped[str] = mapped_column(Text, nullable=False)
    policy_name: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simulation_spec_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.simulation_specs.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    segment: Mapped[str] = mapped_column(Text, nullable=False)
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    candidate_config_hash: Mapped[str | None] = mapped_column(Text)
    dataset_values_hash: Mapped[str | None] = mapped_column(Text)
    prediction_hash: Mapped[str | None] = mapped_column(Text)
    values_hash: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    benchmark: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimulationNavDaily(Base):
    __tablename__ = "simulation_nav_daily"
    __table_args__ = (
        UniqueConstraint("simulation_run_id", "as_of_date", name="uq_portfolio_sim_nav_daily"),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simulation_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.simulation_runs.id", ondelete="CASCADE"), nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    nav: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    gross_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    cash_weight: Mapped[float] = mapped_column(Float, nullable=False)
    peak_nav: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown: Mapped[float] = mapped_column(Float, nullable=False)


class SimulationPositionDaily(Base):
    __tablename__ = "simulation_positions_daily"
    __table_args__ = (
        UniqueConstraint(
            "simulation_run_id",
            "as_of_date",
            "instrument_id",
            name="uq_portfolio_sim_positions_daily",
        ),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simulation_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.simulation_runs.id", ondelete="CASCADE"), nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    instrument_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    market_price: Mapped[float | None] = mapped_column(Float)
    market_value: Mapped[float | None] = mapped_column(Float)
    weight: Mapped[float | None] = mapped_column(Float)


class SimulationOrder(Base):
    __tablename__ = "simulation_orders"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simulation_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.simulation_runs.id", ondelete="CASCADE"), nullable=False
    )
    decision_date: Mapped[date] = mapped_column(Date, nullable=False)
    execution_date: Mapped[date] = mapped_column(Date, nullable=False)
    instrument_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    target_weight: Mapped[float] = mapped_column(Float, nullable=False)
    target_notional: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    prediction_date: Mapped[date | None] = mapped_column(Date)
    predicted_return_20d: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    policy_name: Mapped[str | None] = mapped_column(Text)
    fold_id: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)


class SimulationFill(Base):
    __tablename__ = "simulation_fills"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simulation_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.simulation_runs.id", ondelete="CASCADE"), nullable=False
    )
    execution_date: Mapped[date] = mapped_column(Date, nullable=False)
    decision_date: Mapped[date | None] = mapped_column(Date)
    instrument_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    raw_open: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price: Mapped[float] = mapped_column(Float, nullable=False)
    notional: Mapped[float] = mapped_column(Float, nullable=False)
    commission: Mapped[float] = mapped_column(Float, nullable=False)
    slippage_cost: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)


class SimulationCaEvent(Base):
    __tablename__ = "simulation_ca_events"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simulation_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.simulation_runs.id", ondelete="CASCADE"), nullable=False
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    instrument_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    factor: Mapped[str] = mapped_column(Text, nullable=False)
    quantity_before: Mapped[float] = mapped_column(Float, nullable=False)
    quantity_after: Mapped[float] = mapped_column(Float, nullable=False)
