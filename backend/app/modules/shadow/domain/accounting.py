"""Shadow position cost-basis helpers (framework-free, Decimal)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PositionState:
    quantity: Decimal
    lots: int
    lot_size: int
    avg_entry: Decimal
    cost_basis: Decimal
    realized_pnl: Decimal


def empty_position(*, lot_size: int) -> PositionState:
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    return PositionState(
        quantity=Decimal("0"),
        lots=0,
        lot_size=lot_size,
        avg_entry=Decimal("0"),
        cost_basis=Decimal("0"),
        realized_pnl=Decimal("0"),
    )


def apply_buy(
    state: PositionState | None,
    *,
    units: Decimal,
    fill_price: Decimal,
    fee: Decimal = Decimal("0"),
    lot_size: int,
) -> PositionState:
    if units <= 0 or fill_price <= 0 or lot_size <= 0:
        raise ValueError("buy requires positive units, price, lot_size")
    if int(units) % lot_size != 0:
        raise ValueError("units must be divisible by lot_size")
    lots = int(units) // lot_size
    spend = units * fill_price + fee
    if state is None or state.quantity <= 0:
        return PositionState(
            quantity=units,
            lots=lots,
            lot_size=lot_size,
            avg_entry=fill_price if fee == 0 else (spend / units),
            cost_basis=spend,
            realized_pnl=Decimal("0"),
        )
    if state.lot_size != lot_size:
        raise ValueError("lot_size mismatch on existing position")
    new_qty = state.quantity + units
    new_cost = state.cost_basis + spend
    return PositionState(
        quantity=new_qty,
        lots=int(new_qty) // lot_size,
        lot_size=lot_size,
        avg_entry=new_cost / new_qty,
        cost_basis=new_cost,
        realized_pnl=state.realized_pnl,
    )


def apply_sell(
    state: PositionState,
    *,
    units: Decimal,
    fill_price: Decimal,
    fee: Decimal = Decimal("0"),
) -> tuple[PositionState, Decimal]:
    """Return (new_state, realized_pnl_this_trade). Full close → quantity 0."""
    if units <= 0 or fill_price <= 0:
        raise ValueError("sell requires positive units and price")
    if units > state.quantity:
        raise ValueError("cannot sell more than held")
    if int(units) % state.lot_size != 0:
        raise ValueError("units must be divisible by lot_size")

    cost_removed = state.avg_entry * units
    proceeds = units * fill_price - fee
    realized = proceeds - cost_removed
    remaining = state.quantity - units
    if remaining <= 0:
        closed = PositionState(
            quantity=Decimal("0"),
            lots=0,
            lot_size=state.lot_size,
            avg_entry=Decimal("0"),
            cost_basis=Decimal("0"),
            realized_pnl=state.realized_pnl + realized,
        )
        return closed, realized
    new_cost = state.cost_basis - cost_removed
    new_state = PositionState(
        quantity=remaining,
        lots=int(remaining) // state.lot_size,
        lot_size=state.lot_size,
        avg_entry=state.avg_entry,
        cost_basis=new_cost,
        realized_pnl=state.realized_pnl + realized,
    )
    return new_state, realized
