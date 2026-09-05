"""Research-only asset allocation and realistic integer-lot preview."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.modules.investment.domain.fixed_income import TransactionCostProfile, affordable_lots


class AssetSleeve(StrEnum):
    EQUITY_ALPHA = "EQUITY_ALPHA"
    FIXED_INCOME = "FIXED_INCOME"
    CASH = "CASH"


class AssetAllocationPolicy(Protocol):
    def weights(self, expected_excess_return: float | None = None) -> dict[AssetSleeve, float]: ...


@dataclass(frozen=True)
class StaticAllocationPolicy:
    equity: float
    fixed_income: float
    cash: float

    def weights(self, expected_excess_return: float | None = None) -> dict[AssetSleeve, float]:
        values = {
            AssetSleeve.EQUITY_ALPHA: self.equity,
            AssetSleeve.FIXED_INCOME: self.fixed_income,
            AssetSleeve.CASH: self.cash,
        }
        if any(value < 0 for value in values.values()) or abs(sum(values.values()) - 1) > 1e-9:
            raise ValueError("allocation weights must be non-negative and sum to one")
        return values


EQUITY_ONLY = StaticAllocationPolicy(1, 0, 0)
FIXED_INCOME_ONLY = StaticAllocationPolicy(0, 1, 0)
CASH_ONLY = StaticAllocationPolicy(0, 0, 1)
DEFAULT_TRANSACTION_COSTS = TransactionCostProfile(Decimal("5"))


@dataclass(frozen=True)
class HurdleGatedEquityPolicy:
    fallback: StaticAllocationPolicy = CASH_ONLY

    def weights(self, expected_excess_return: float | None = None) -> dict[AssetSleeve, float]:
        return (
            EQUITY_ONLY.weights()
            if expected_excess_return is not None and expected_excess_return > 0
            else self.fallback.weights()
        )


@dataclass(frozen=True)
class AllocationCandidate:
    symbol: str
    sleeve: AssetSleeve
    price: Decimal
    lot_size: int
    target_weight: Decimal


@dataclass(frozen=True)
class AllocatedPosition:
    symbol: str
    sleeve: AssetSleeve
    lots: int
    units: int
    execution_price: Decimal
    notional: Decimal
    fees: Decimal
    cash_used: Decimal
    diagnostic: str | None = None


@dataclass(frozen=True)
class AllocationResult:
    starting_cash: Decimal
    positions: tuple[AllocatedPosition, ...]
    fees: Decimal
    cash_remainder: Decimal
    diagnostics: tuple[str, ...]
    mode: str = "REALISTIC_LOT_SIMULATION_V0"


def allocate_integer_lots(
    candidates: Sequence[AllocationCandidate],
    *,
    capital: Decimal = Decimal("100000"),
    costs: TransactionCostProfile = DEFAULT_TRANSACTION_COSTS,
) -> AllocationResult:
    if capital < 0:
        raise ValueError("capital must be non-negative")
    cash = capital
    positions: list[AllocatedPosition] = []
    diagnostics: list[str] = []
    for candidate in candidates:
        if candidate.price <= 0 or candidate.lot_size <= 0 or candidate.target_weight < 0:
            diagnostics.append(f"{candidate.symbol}:invalid_input")
            continue
        target_cash = min(cash, capital * candidate.target_weight)
        lot_price = costs.execution_price(candidate.price, "BUY") * candidate.lot_size
        lots = affordable_lots(target_cash, lot_price, costs)
        if lots == 0:
            reason = "lot_too_expensive" if lot_price > target_cash else "position_too_small"
            diagnostics.append(f"{candidate.symbol}:{reason}")
            continue
        notional = lot_price * lots
        fees = costs.fee(notional)
        used = notional + fees
        if used > cash:
            diagnostics.append(f"{candidate.symbol}:insufficient_cash")
            continue
        cash -= used
        positions.append(
            AllocatedPosition(
                symbol=candidate.symbol,
                sleeve=candidate.sleeve,
                lots=lots,
                units=lots * candidate.lot_size,
                execution_price=costs.execution_price(candidate.price, "BUY"),
                notional=notional,
                fees=fees,
                cash_used=used,
            )
        )
    return AllocationResult(
        starting_cash=capital,
        positions=tuple(positions),
        fees=sum((p.fees for p in positions), Decimal("0")),
        cash_remainder=cash,
        diagnostics=tuple(diagnostics),
    )
