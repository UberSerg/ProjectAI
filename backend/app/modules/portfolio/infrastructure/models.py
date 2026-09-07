"""Manual Portfolio V1 persistence (schema portfolio)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.market.models import Base


class ManualPortfolio(Base):
    __tablename__ = "manual_portfolios"
    __table_args__ = {"schema": "portfolio"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="MANUAL")
    base_currency: Mapped[str] = mapped_column(Text, nullable=False, default="RUB")
    cash_rub: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    positions: Mapped[list[ManualPosition]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class ManualPosition(Base):
    __tablename__ = "manual_positions"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "instrument_id",
            name="uq_portfolio_manual_positions_portfolio_instrument",
        ),
        {"schema": "portfolio"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("portfolio.manual_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("market.instruments.id", ondelete="RESTRICT"), nullable=False
    )
    units: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    average_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    note: Mapped[str | None] = mapped_column(Text)
    non_standard_lot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    portfolio: Mapped[ManualPortfolio] = relationship(back_populates="positions")
