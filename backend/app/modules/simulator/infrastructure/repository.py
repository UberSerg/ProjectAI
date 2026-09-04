"""Persist and read Historical Simulator V0 runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.simulator.application.engine import SimulationResult
from app.modules.simulator.infrastructure.models import (
    SimulationCaEvent,
    SimulationFill,
    SimulationNavDaily,
    SimulationOrder,
    SimulationPositionDaily,
    SimulationRun,
    SimulationSpec,
)


def upsert_spec(session: Session, result: SimulationResult) -> SimulationSpec:
    existing = session.scalar(
        select(SimulationSpec).where(SimulationSpec.config_hash == result.config_hash)
    )
    if existing is not None:
        return existing
    row = SimulationSpec(
        config_hash=result.config_hash,
        segment=result.spec.segment,
        policy_name=result.spec.policy_name,
        payload=result.spec.to_dict(),
    )
    session.add(row)
    session.flush()
    return row


def persist_simulation_result(session: Session, result: SimulationResult) -> SimulationRun:
    spec_row = upsert_spec(session, result)
    snaps = result.ledger.snapshots
    run = SimulationRun(
        simulation_spec_id=spec_row.id,
        status="SUCCESS",
        segment=result.spec.segment,
        date_from=snaps[0].as_of if snaps else None,
        date_to=snaps[-1].as_of if snaps else None,
        candidate_config_hash=result.provenance.get("candidate_config_hash"),
        dataset_values_hash=result.provenance.get("dataset_values_hash"),
        prediction_hash=result.provenance.get("prediction_hash"),
        values_hash=result.values_hash,
        metrics=result.metrics,
        benchmark=result.benchmark,
        provenance=result.provenance,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()

    for snap in snaps:
        session.add(
            SimulationNavDaily(
                simulation_run_id=run.id,
                as_of_date=snap.as_of,
                nav=snap.nav,
                cash=snap.cash,
                gross_exposure=snap.gross_exposure,
                cash_weight=snap.cash_weight,
                peak_nav=snap.peak_nav,
                drawdown=snap.drawdown,
            )
        )
        for pos in snap.positions.values():
            session.add(
                SimulationPositionDaily(
                    simulation_run_id=run.id,
                    as_of_date=snap.as_of,
                    instrument_id=int(pos["instrument_id"]),
                    ticker=str(pos["ticker"]),
                    quantity=float(pos["quantity"]),
                    market_price=pos.get("market_price"),
                    market_value=pos.get("market_value"),
                    weight=pos.get("weight"),
                )
            )

    for order in result.ledger.orders:
        session.add(
            SimulationOrder(
                simulation_run_id=run.id,
                decision_date=order.decision_date,
                execution_date=order.execution_date,
                instrument_id=order.instrument_id,
                ticker=order.ticker,
                side=order.side,
                target_weight=order.target_weight,
                target_notional=order.target_notional,
                quantity=order.quantity,
                reason=order.reason,
                prediction_date=order.prediction_date,
                predicted_return_20d=order.predicted_return_20d,
                rank=order.rank,
                policy_name=order.policy_name,
                fold_id=order.fold_id,
                metadata_json=dict(order.metadata or {}),
            )
        )

    for fill in result.ledger.fills:
        session.add(
            SimulationFill(
                simulation_run_id=run.id,
                execution_date=fill.execution_date,
                decision_date=fill.decision_date,
                instrument_id=fill.instrument_id,
                ticker=fill.ticker,
                side=fill.side,
                quantity=fill.quantity,
                raw_open=fill.raw_open,
                fill_price=fill.fill_price,
                notional=fill.notional,
                commission=fill.commission,
                slippage_cost=fill.slippage_cost,
                metadata_json=dict(fill.metadata or {}),
            )
        )

    for ev in result.ledger.ca_events:
        session.add(
            SimulationCaEvent(
                simulation_run_id=run.id,
                event_date=date_parse(ev["date"]),
                instrument_id=int(ev["instrument_id"]),
                ticker=str(ev["ticker"]),
                event_type=str(ev["event_type"]),
                factor=str(ev["factor"]),
                quantity_before=float(ev["quantity_before"]),
                quantity_after=float(ev["quantity_after"]),
            )
        )

    session.flush()
    return run


def date_parse(value: str):
    from datetime import date

    return date.fromisoformat(value)


def list_runs(session: Session, *, limit: int = 50) -> list[SimulationRun]:
    return list(
        session.scalars(
            select(SimulationRun).order_by(SimulationRun.id.desc()).limit(limit)
        )
    )


def get_run(session: Session, run_id: int) -> SimulationRun | None:
    return session.get(SimulationRun, run_id)


def get_nav_series(session: Session, run_id: int) -> list[SimulationNavDaily]:
    return list(
        session.scalars(
            select(SimulationNavDaily)
            .where(SimulationNavDaily.simulation_run_id == run_id)
            .order_by(SimulationNavDaily.as_of_date)
        )
    )


def get_fills(session: Session, run_id: int) -> list[SimulationFill]:
    return list(
        session.scalars(
            select(SimulationFill)
            .where(SimulationFill.simulation_run_id == run_id)
            .order_by(SimulationFill.execution_date, SimulationFill.id)
        )
    )


def get_orders(session: Session, run_id: int) -> list[SimulationOrder]:
    return list(
        session.scalars(
            select(SimulationOrder)
            .where(SimulationOrder.simulation_run_id == run_id)
            .order_by(SimulationOrder.decision_date, SimulationOrder.id)
        )
    )


def get_positions_for_date(
    session: Session, run_id: int, as_of_date
) -> list[SimulationPositionDaily]:
    return list(
        session.scalars(
            select(SimulationPositionDaily).where(
                SimulationPositionDaily.simulation_run_id == run_id,
                SimulationPositionDaily.as_of_date == as_of_date,
            )
        )
    )


def run_to_summary(run: SimulationRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "segment": run.segment,
        "date_from": run.date_from.isoformat() if run.date_from else None,
        "date_to": run.date_to.isoformat() if run.date_to else None,
        "candidate_config_hash": run.candidate_config_hash,
        "dataset_values_hash": run.dataset_values_hash,
        "prediction_hash": run.prediction_hash,
        "values_hash": run.values_hash,
        "metrics": run.metrics,
        "benchmark": run.benchmark,
        "provenance": run.provenance,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
