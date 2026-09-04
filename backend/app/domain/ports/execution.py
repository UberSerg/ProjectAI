"""Execution ports — Order Intent → replaceable Execution Adapter."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.domain.ports.technical import JsonObject

OrderSide = Literal["BUY", "SELL"]


@dataclass(slots=True, frozen=True)
class OrderIntent:
    """Desired trade — not a broker order."""

    decision_date: date
    execution_date: date
    instrument_id: int
    ticker: str
    side: OrderSide
    target_weight: float
    target_notional: float
    quantity: float
    reason: str
    prediction_date: date | None = None
    predicted_return_20d: float | None = None
    rank: int | None = None
    policy_name: str | None = None
    fold_id: str | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class HistoricalFill:
    """Fill from Historical Execution Adapter (research, not broker)."""

    execution_date: date
    instrument_id: int
    ticker: str
    side: OrderSide
    quantity: float
    raw_open: float
    fill_price: float
    notional: float
    commission: float
    slippage_cost: float
    decision_date: date | None = None
    metadata: JsonObject = field(default_factory=dict)


class ExecutionAdapter(ABC):
    @abstractmethod
    def fill(
        self,
        intent: OrderIntent,
        *,
        raw_open: float | None,
        commission_bps: float,
        slippage_bps: float,
    ) -> HistoricalFill | None:
        """Return fill or None when price missing / trade skipped."""
        raise NotImplementedError
