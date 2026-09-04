"""Read-only Historical Simulator V0 API (dashboard contract)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.infrastructure.db.session import core_session
from app.modules.simulator.application.dashboard_read import (
    day_inspector_payload,
    imoex_benchmark_series,
)
from app.modules.simulator.infrastructure.repository import (
    get_fills,
    get_nav_series,
    get_orders,
    get_positions_for_date,
    get_run,
    list_cost_sensitivity_siblings,
    list_runs,
    rebalance_dates,
    run_to_summary,
)

router = APIRouter()


@router.get("/runs")
def api_list_runs(limit: int = Query(50, ge=1, le=200)) -> dict:
    with core_session() as session:
        rows = list_runs(session, limit=limit)
        return {"items": [run_to_summary(session, r) for r in rows]}


@router.get("/runs/{run_id}")
def api_get_run(run_id: int) -> dict:
    with core_session() as session:
        run = get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="simulation run not found")
        return run_to_summary(session, run)


@router.get("/runs/{run_id}/nav")
def api_get_nav(run_id: int) -> dict:
    with core_session() as session:
        run = get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="simulation run not found")
        series = get_nav_series(session, run_id)
        if not series:
            return {
                "run_id": run_id,
                "benchmark": run.benchmark,
                "benchmark_series": [],
                "rebalance_dates": [],
                "date_from": None,
                "date_to": None,
                "items": [],
            }
        d0 = series[0].as_of_date
        d1 = series[-1].as_of_date
        bench_series = imoex_benchmark_series(session, date_from=d0, date_to=d1)
        return {
            "run_id": run_id,
            "benchmark": run.benchmark,
            "benchmark_series": bench_series,
            "rebalance_dates": rebalance_dates(session, run_id),
            "date_from": d0.isoformat(),
            "date_to": d1.isoformat(),
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


@router.get("/runs/{run_id}/day")
def api_get_day(run_id: int, as_of: date) -> dict:
    with core_session() as session:
        if get_run(session, run_id) is None:
            raise HTTPException(status_code=404, detail="simulation run not found")
        return day_inspector_payload(session, run_id, as_of)


@router.get("/runs/{run_id}/cost-sensitivity")
def api_cost_sensitivity(run_id: int) -> dict:
    """Sibling SUCCESS runs (same segment + candidate) with different friction assumptions."""
    with core_session() as session:
        run = get_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="simulation run not found")
        siblings = list_cost_sensitivity_siblings(session, run)
        items = []
        for sib in siblings:
            summary = run_to_summary(session, sib)
            spec = summary.get("spec") or {}
            metrics = summary.get("metrics") or {}
            items.append(
                {
                    "run_id": sib.id,
                    "commission_bps": spec.get("commission_bps"),
                    "slippage_bps": spec.get("slippage_bps"),
                    "cost_sensitivity_label": spec.get("cost_sensitivity_label"),
                    "total_price_return": metrics.get("total_price_return"),
                    "final_nav": metrics.get("final_nav"),
                    "max_drawdown": metrics.get("max_drawdown"),
                    "is_current": sib.id == run_id,
                }
            )
        items.sort(key=lambda x: (float(x.get("commission_bps") or 0.0), float(x.get("slippage_bps") or 0.0)))
        return {"run_id": run_id, "segment": run.segment, "items": items}


@router.get("/runs/{run_id}/fills")
def api_get_fills(run_id: int) -> dict:
    from sqlalchemy import select

    from app.infrastructure.market.models import Instrument

    with core_session() as session:
        if get_run(session, run_id) is None:
            raise HTTPException(status_code=404, detail="simulation run not found")
        fills = get_fills(session, run_id)
        orders = get_orders(session, run_id)
        order_by_key = {
            (o.execution_date, o.instrument_id, o.side): o for o in orders
        }
        instrument_ids = {f.instrument_id for f in fills}
        name_by_id: dict[int, str] = {}
        if instrument_ids:
            name_by_id = {
                int(iid): str(name)
                for iid, name in session.execute(
                    select(Instrument.id, Instrument.name).where(Instrument.id.in_(instrument_ids))
                )
            }
        items = []
        for f in fills:
            linked = order_by_key.get((f.execution_date, f.instrument_id, f.side))
            meta = linked.metadata_json if linked and isinstance(linked.metadata_json, dict) else None
            items.append(
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
                    "prediction_date": linked.prediction_date.isoformat()
                    if linked and linked.prediction_date
                    else None,
                    "predicted_return_20d": linked.predicted_return_20d if linked else None,
                    "rank": linked.rank if linked else None,
                    "policy_name": linked.policy_name if linked else None,
                    "target_weight": linked.target_weight if linked else None,
                    "fold_id": linked.fold_id if linked else None,
                    "reason": linked.reason if linked else None,
                    "metadata": meta,
                    "eligible_count": (meta or {}).get("eligible_n"),
                    "display_name": name_by_id.get(f.instrument_id),
                }
            )
        return {"run_id": run_id, "items": items}


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
