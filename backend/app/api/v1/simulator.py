"""Read-only Historical Simulator V0 API (dashboard contract)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.infrastructure.db.session import core_session
from app.modules.simulator.infrastructure.repository import (
    get_fills,
    get_nav_series,
    get_orders,
    get_positions_for_date,
    get_run,
    list_runs,
    run_to_summary,
)

router = APIRouter()


@router.get("/runs")
def api_list_runs(limit: int = Query(50, ge=1, le=200)) -> dict:
    with core_session() as session:
        rows = list_runs(session, limit=limit)
        return {"items": [run_to_summary(r) for r in rows]}


@router.get("/runs/{run_id}")
def api_get_run(run_id: int) -> dict:
    with core_session() as session:
        run = get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="simulation run not found")
        return run_to_summary(run)


@router.get("/runs/{run_id}/nav")
def api_get_nav(run_id: int) -> dict:
    with core_session() as session:
        run = get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="simulation run not found")
        series = get_nav_series(session, run_id)
        return {
            "run_id": run_id,
            "benchmark": run.benchmark,
            "items": [
                {
                    "date": r.as_of_date.isoformat(),
                    "nav": r.nav,
                    "cash": r.cash,
                    "gross_exposure": r.gross_exposure,
                    "cash_weight": r.cash_weight,
                    "peak_nav": r.peak_nav,
                    "drawdown": r.drawdown,
                }
                for r in series
            ],
        }


@router.get("/runs/{run_id}/fills")
def api_get_fills(run_id: int) -> dict:
    with core_session() as session:
        if get_run(session, run_id) is None:
            raise HTTPException(status_code=404, detail="simulation run not found")
        fills = get_fills(session, run_id)
        return {
            "run_id": run_id,
            "items": [
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


@router.get("/runs/{run_id}/orders")
def api_get_orders(run_id: int) -> dict:
    with core_session() as session:
        if get_run(session, run_id) is None:
            raise HTTPException(status_code=404, detail="simulation run not found")
        orders = get_orders(session, run_id)
        return {
            "run_id": run_id,
            "items": [
                {
                    "decision_date": o.decision_date.isoformat(),
                    "execution_date": o.execution_date.isoformat(),
                    "instrument_id": o.instrument_id,
                    "ticker": o.ticker,
                    "side": o.side,
                    "target_weight": o.target_weight,
                    "target_notional": o.target_notional,
                    "quantity": o.quantity,
                    "reason": o.reason,
                    "prediction_date": o.prediction_date.isoformat() if o.prediction_date else None,
                    "predicted_return_20d": o.predicted_return_20d,
                    "rank": o.rank,
                    "policy_name": o.policy_name,
                    "fold_id": o.fold_id,
                    "metadata": o.metadata_json,
                }
                for o in orders
            ],
        }


@router.get("/runs/{run_id}/positions")
def api_get_positions(
    run_id: int,
    as_of: date,
) -> dict:
    """Query param: as_of=YYYY-MM-DD."""
    with core_session() as session:
        if get_run(session, run_id) is None:
            raise HTTPException(status_code=404, detail="simulation run not found")
        rows = get_positions_for_date(session, run_id, as_of)
        return {
            "run_id": run_id,
            "as_of": as_of.isoformat(),
            "items": [
                {
                    "instrument_id": p.instrument_id,
                    "ticker": p.ticker,
                    "quantity": p.quantity,
                    "market_price": p.market_price,
                    "market_value": p.market_value,
                    "weight": p.weight,
                }
                for p in rows
            ],
        }
