"""Shared helpers for lot-aware Shadow specs and position JSON updates."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.modules.shadow.domain.accounting import PositionState, apply_buy, apply_sell

EXECUTION_VERSION_LOT_AWARE_V2 = "LOT_AWARE_V2"


def is_lot_aware_spec(spec: Any) -> bool:
    """True when fractional_shares is False or payload marks LOT_AWARE_V2."""
    if spec is None:
        return False
    if bool(getattr(spec, "fractional_shares", True)) is False:
        return True
    payload = getattr(spec, "payload", None) or {}
    if isinstance(payload, dict):
        if payload.get("execution_version") == EXECUTION_VERSION_LOT_AWARE_V2:
            return True
        if payload.get("fractional_shares") is False:
            return True
    return False


def positions_dict(portfolio: Any) -> dict[str, dict[str, Any]]:
    raw = portfolio.positions or {}
    return {str(k): dict(v) for k, v in raw.items()}


def position_qty(portfolio: Any, instrument_id: int) -> float:
    row = positions_dict(portfolio).get(str(instrument_id))
    return float(row["quantity"]) if row else 0.0


def set_fractional_position(
    portfolio: Any, instrument_id: int, ticker: str, qty: float
) -> None:
    """V1 path — quantity only."""
    pos = positions_dict(portfolio)
    key = str(instrument_id)
    if abs(qty) < 1e-12:
        pos.pop(key, None)
    else:
        pos[key] = {"instrument_id": instrument_id, "ticker": ticker, "quantity": float(qty)}
    portfolio.positions = pos


def _state_to_dict(
    state: PositionState, *, instrument_id: int, ticker: str
) -> dict[str, float | int | str]:
    return {
        "instrument_id": int(instrument_id),
        "ticker": ticker,
        "quantity": float(state.quantity),
        "lots": int(state.lots),
        "lot_size": int(state.lot_size),
        "avg_entry": float(state.avg_entry),
        "cost_basis": float(state.cost_basis),
        "realized_pnl": float(state.realized_pnl),
    }


def _state_from_row(row: dict[str, Any], *, lot_size: int) -> PositionState | None:
    qty = Decimal(str(row.get("quantity") or 0))
    if qty <= 0:
        return None
    ls = int(row.get("lot_size") or lot_size)
    return PositionState(
        quantity=qty,
        lots=int(row["lots"]) if row.get("lots") is not None else int(qty) // ls,
        lot_size=ls,
        avg_entry=Decimal(str(row.get("avg_entry") or 0)),
        cost_basis=Decimal(str(row.get("cost_basis") or 0)),
        realized_pnl=Decimal(str(row.get("realized_pnl") or 0)),
    )


def apply_lot_aware_fill_to_portfolio(
    portfolio: Any,
    *,
    instrument_id: int,
    ticker: str,
    side: str,
    quantity: float,
    fill_price: float,
    commission: float,
    lot_size: int,
) -> PositionState | None:
    """Update positions JSON only (cash is caller's job). Enforces lot alignment."""
    units = Decimal(str(quantity))
    price = Decimal(str(fill_price))
    fee = Decimal(str(commission))
    if lot_size <= 0:
        raise ValueError("lot_size must be positive for lot-aware fill")
    if int(units) % int(lot_size) != 0:
        raise ValueError(f"fill quantity {quantity} not divisible by lot_size {lot_size}")

    pos = positions_dict(portfolio)
    key = str(instrument_id)
    existing = pos.get(key)
    state = _state_from_row(existing, lot_size=lot_size) if existing else None

    if side.upper() == "BUY":
        new_state = apply_buy(
            state, units=units, fill_price=price, fee=fee, lot_size=lot_size
        )
    elif side.upper() == "SELL":
        if state is None:
            raise ValueError("no position to sell")
        new_state, _realized = apply_sell(state, units=units, fill_price=price, fee=fee)
    else:
        raise ValueError(f"unsupported side: {side}")

    if new_state.quantity <= 0:
        pos.pop(key, None)
        portfolio.positions = pos
        return None
    pos[key] = _state_to_dict(new_state, instrument_id=instrument_id, ticker=ticker)
    portfolio.positions = pos
    return new_state
