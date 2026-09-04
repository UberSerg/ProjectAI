"""Read-model helpers for Simulator Dashboard (no policy recompute)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument
from app.modules.simulator.infrastructure.models import (
    SimulationFill,
    SimulationNavDaily,
    SimulationOrder,
)
from app.modules.simulator.infrastructure.repository import (
    get_fills,
    get_nav_series,
    get_orders,
    get_positions_for_date,
)


def imoex_benchmark_series(
    session: Session,
    *,
    date_from: date,
    date_to: date,
) -> list[dict[str, Any]]:
    """RAW IMOEX daily closes aligned to [date_from, date_to]. Price index only."""
    imoex = session.scalar(select(Instrument).where(Instrument.symbol == "IMOEX"))
    if imoex is None:
        return []
    start_dt = datetime.combine(date_from, time.min, tzinfo=UTC)
    end_dt = datetime.combine(date_to, time.max, tzinfo=UTC)
    candles = list(
        session.scalars(
            select(Candle)
            .where(
                Candle.instrument_id == imoex.id,
                Candle.timeframe == "1d",
                Candle.timestamp >= start_dt,
                Candle.timestamp <= end_dt,
            )
            .order_by(Candle.timestamp)
        )
    )
    out: list[dict[str, Any]] = []
    for c in candles:
        d = c.timestamp.date() if hasattr(c.timestamp, "date") else date.fromisoformat(str(c.timestamp)[:10])
        if c.close is None:
            continue
        out.append({"date": d.isoformat(), "close": float(c.close)})
    return out


def day_inspector_payload(session: Session, run_id: int, as_of: date) -> dict[str, Any]:
    nav_rows = get_nav_series(session, run_id)
    nav = next((r for r in nav_rows if r.as_of_date == as_of), None)
    positions = get_positions_for_date(session, run_id, as_of)
    orders = [
        o
        for o in get_orders(session, run_id)
        if o.decision_date == as_of or o.execution_date == as_of
    ]
    fills = [f for f in get_fills(session, run_id) if f.execution_date == as_of]
    rebalance = any(o.decision_date == as_of for o in orders)
    return {
        "run_id": run_id,
        "as_of": as_of.isoformat(),
        "nav": None
        if nav is None
        else {
            "nav": nav.nav,
            "cash": nav.cash,
            "gross_exposure": nav.gross_exposure,
            "cash_weight": nav.cash_weight,
            "peak_nav": nav.peak_nav,
            "drawdown": nav.drawdown,
            "positions_count": len(positions),
        },
        "rebalance": rebalance,
        "positions": [
            {
                "instrument_id": p.instrument_id,
                "ticker": p.ticker,
                "quantity": p.quantity,
                "market_price": p.market_price,
                "market_value": p.market_value,
                "weight": p.weight,
            }
            for p in sorted(positions, key=lambda x: -(x.weight or 0.0))
        ],
        "orders": [
            {
                "decision_date": o.decision_date.isoformat(),
                "execution_date": o.execution_date.isoformat(),
                "instrument_id": o.instrument_id,
                "ticker": o.ticker,
                "side": o.side,
                "target_weight": o.target_weight,
                "quantity": o.quantity,
                "predicted_return_20d": o.predicted_return_20d,
                "rank": o.rank,
                "policy_name": o.policy_name,
                "prediction_date": o.prediction_date.isoformat() if o.prediction_date else None,
                "fold_id": o.fold_id,
                "reason": o.reason,
                "metadata": o.metadata_json,
            }
            for o in orders
        ],
        "fills": [
            {
                "execution_date": f.execution_date.isoformat(),
                "decision_date": f.decision_date.isoformat() if f.decision_date else None,
                "instrument_id": f.instrument_id,
                "ticker": f.ticker,
                "side": f.side,
                "quantity": f.quantity,
                "raw_open": f.raw_open,
                "fill_price": f.fill_price,
                "notional": f.notional,
                "commission": f.commission,
                "slippage_cost": f.slippage_cost,
            }
            for f in fills
        ],
    }


# Silence unused import warnings if type checkers look at models only used in annotations
_ = (SimulationFill, SimulationNavDaily, SimulationOrder)
