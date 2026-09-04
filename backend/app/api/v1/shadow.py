"""Read-only Shadow Portfolio V0 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.infrastructure.db.session import core_session
from app.infrastructure.market.models import Instrument
from app.modules.market.application.workflows import create_workflow
from app.modules.shadow.application.service import initialize_shadow_portfolios
from app.modules.shadow.config import SHADOW_KIND
from app.modules.shadow.infrastructure.models import (
    ShadowDecision,
    ShadowFill,
    ShadowNavDaily,
    ShadowOrder,
    ShadowPortfolio,
    ShadowPortfolioSpec,
)
from app.worker import tasks as worker_tasks

router = APIRouter()


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _date(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _position_count(positions: Any) -> int:
    if not isinstance(positions, dict):
        return 0
    return len(positions)


def _portfolio_summary(
    portfolio: ShadowPortfolio,
    spec: ShadowPortfolioSpec,
    *,
    pending: int,
    fills: int,
) -> dict[str, Any]:
    cash = float(portfolio.cash)
    peak = float(portfolio.peak_nav or cash)
    # Cash-only / no MTM yet: NAV ≈ cash when no positions
    pos_count = _position_count(portfolio.positions)
    nav = cash if pos_count == 0 else cash  # market value requires NAV rows; cash is source until fills
    return {
        "id": str(portfolio.id),
        "name": spec.name,
        "status": portfolio.status,
        "policy_name": spec.policy_name,
        "risk_name": spec.risk_name,
        "activated_at": _dt(portfolio.activated_at),
        "cash": cash,
        "nav": nav,
        "peak_nav": peak,
        "initial_capital": float(spec.initial_capital),
        "risk_mode": portfolio.risk_mode,
        "exposure_cap": float(portfolio.exposure_cap),
        "pending_orders": pending,
        "fills": fills,
        "position_count": pos_count,
        "last_processed_market_date": _date(portfolio.last_processed_market_date),
        "first_forward_batch_id": portfolio.first_forward_batch_id,
        "first_forward_as_of_date": _date(portfolio.first_forward_as_of_date),
        "last_decision_iso_week": portfolio.last_decision_iso_week,
        "last_processed_prediction_batch_id": portfolio.last_processed_prediction_batch_id,
        "experiment_group": spec.experiment_group,
        "dd_trigger": spec.dd_trigger,
        "dd_recovery": spec.dd_recovery,
        "dd_risk_off_gross": spec.dd_risk_off_gross,
        "dd_normal_gross": spec.dd_normal_gross,
        "kind": SHADOW_KIND,
    }


class ShadowPortfolioSummary(BaseModel):
    id: str
    name: str
    status: str
    policy_name: str
    risk_name: str
    activated_at: str | None
    cash: float
    nav: float = 0.0
    peak_nav: float = 0.0
    initial_capital: float = 1_000_000.0
    risk_mode: str
    exposure_cap: float
    pending_orders: int
    fills: int
    position_count: int = 0
    last_processed_market_date: str | None
    first_forward_batch_id: int | None = None
    first_forward_as_of_date: str | None = None
    last_decision_iso_week: str | None = None
    last_processed_prediction_batch_id: int | None = None
    experiment_group: str | None = None
    dd_trigger: float | None = None
    dd_recovery: float | None = None
    dd_risk_off_gross: float | None = None
    dd_normal_gross: float | None = None
    kind: str = SHADOW_KIND


@router.get("/overview")
def shadow_overview() -> dict[str, Any]:
    """Dashboard read-model: portfolios + experiment identity (facts only)."""
    with core_session() as session:
        rows = session.execute(
            select(ShadowPortfolio, ShadowPortfolioSpec)
            .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
            .order_by(ShadowPortfolio.id)
        ).all()
        portfolios: list[dict[str, Any]] = []
        activated_at = None
        experiment_group = None
        for portfolio, spec in rows:
            pending = len(
                list(
                    session.scalars(
                        select(ShadowOrder).where(
                            ShadowOrder.portfolio_id == portfolio.id,
                            ShadowOrder.status == "PENDING",
                        )
                    )
                )
            )
            fills = len(
                list(
                    session.scalars(
                        select(ShadowFill).where(ShadowFill.portfolio_id == portfolio.id)
                    )
                )
            )
            # Prefer latest NAV row when present
            latest_nav = session.scalar(
                select(ShadowNavDaily)
                .where(ShadowNavDaily.portfolio_id == portfolio.id)
                .order_by(ShadowNavDaily.as_of_date.desc())
                .limit(1)
            )
            summary = _portfolio_summary(portfolio, spec, pending=pending, fills=fills)
            if latest_nav is not None:
                summary["nav"] = float(latest_nav.nav)
                summary["cash"] = float(latest_nav.cash)
                summary["market_value"] = float(latest_nav.market_value)
                summary["drawdown"] = float(latest_nav.drawdown)
                summary["gross_exposure"] = float(latest_nav.gross_exposure)
                summary["nav_as_of"] = latest_nav.as_of_date.isoformat()
            else:
                summary["market_value"] = 0.0
                summary["drawdown"] = 0.0
                summary["gross_exposure"] = 0.0
                summary["nav_as_of"] = None
            portfolios.append(summary)
            if activated_at is None or (
                portfolio.activated_at and portfolio.activated_at < activated_at
            ):
                activated_at = portfolio.activated_at
            experiment_group = experiment_group or spec.experiment_group

        return {
            "kind": SHADOW_KIND,
            "experiment_group": experiment_group,
            "activated_at": _dt(activated_at),
            "automatic_schedule": "not_configured",
            "portfolios": portfolios,
        }


@router.get("/portfolios", response_model=list[ShadowPortfolioSummary])
def list_shadow_portfolios() -> list[ShadowPortfolioSummary]:
    with core_session() as session:
        rows = session.execute(
            select(ShadowPortfolio, ShadowPortfolioSpec)
            .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
            .order_by(ShadowPortfolio.id)
        ).all()
        out: list[ShadowPortfolioSummary] = []
        for portfolio, spec in rows:
            pending = len(
                list(
                    session.scalars(
                        select(ShadowOrder).where(
                            ShadowOrder.portfolio_id == portfolio.id,
                            ShadowOrder.status == "PENDING",
                        )
                    )
                )
            )
            fills = len(
                list(
                    session.scalars(
                        select(ShadowFill).where(ShadowFill.portfolio_id == portfolio.id)
                    )
                )
            )
            out.append(ShadowPortfolioSummary(**_portfolio_summary(portfolio, spec, pending=pending, fills=fills)))
        return out


@router.get("/portfolios/{portfolio_id}")
def get_shadow_portfolio(portfolio_id: int) -> dict[str, Any]:
    with core_session() as session:
        portfolio = session.get(ShadowPortfolio, portfolio_id)
        if portfolio is None:
            raise HTTPException(404, "Shadow portfolio not found")
        spec = session.get(ShadowPortfolioSpec, portfolio.spec_id)
        assert spec is not None
        pending = len(
            list(
                session.scalars(
                    select(ShadowOrder).where(
                        ShadowOrder.portfolio_id == portfolio.id,
                        ShadowOrder.status == "PENDING",
                    )
                )
            )
        )
        fills = len(
            list(session.scalars(select(ShadowFill).where(ShadowFill.portfolio_id == portfolio.id)))
        )
        summary = _portfolio_summary(portfolio, spec, pending=pending, fills=fills)
        summary.update(
            {
                "positions": portfolio.positions,
                "provenance": portfolio.provenance,
                "warnings": portfolio.warnings,
                "config_hash": spec.config_hash,
                "candidate_config_hash": spec.candidate_config_hash,
                "candidate_name": spec.candidate_name,
                "candidate_version": spec.candidate_version,
            }
        )
        return summary


@router.get("/portfolios/{portfolio_id}/nav")
def get_shadow_nav(portfolio_id: int, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[dict]:
    with core_session() as session:
        rows = list(
            session.scalars(
                select(ShadowNavDaily)
                .where(ShadowNavDaily.portfolio_id == portfolio_id)
                .order_by(ShadowNavDaily.as_of_date.desc())
                .limit(limit)
            )
        )
        return [
            {
                "as_of_date": r.as_of_date.isoformat(),
                "cash": r.cash,
                "market_value": r.market_value,
                "nav": r.nav,
                "gross_exposure": r.gross_exposure,
                "drawdown": r.drawdown,
                "peak_nav": r.peak_nav,
                "position_count": r.position_count,
                "benchmark_value": r.benchmark_value,
            }
            for r in reversed(rows)
        ]


@router.get("/portfolios/{portfolio_id}/positions")
def get_shadow_positions(portfolio_id: int) -> dict[str, Any]:
    with core_session() as session:
        portfolio = session.get(ShadowPortfolio, portfolio_id)
        if portfolio is None:
            raise HTTPException(404, "Shadow portfolio not found")
        return {"positions": portfolio.positions or {}}


@router.get("/portfolios/{portfolio_id}/orders")
def get_shadow_orders(portfolio_id: int) -> list[dict]:
    with core_session() as session:
        rows = list(
            session.scalars(
                select(ShadowOrder)
                .where(ShadowOrder.portfolio_id == portfolio_id)
                .order_by(ShadowOrder.id)
            )
        )
        ids = {int(r.instrument_id) for r in rows}
        name_by_id: dict[int, str] = {}
        if ids:
            name_by_id = {
                int(iid): str(name)
                for iid, name in session.execute(
                    select(Instrument.id, Instrument.name).where(Instrument.id.in_(ids))
                )
            }
        return [
            {
                "id": r.id,
                "instrument_id": r.instrument_id,
                "ticker": r.ticker,
                "display_name": name_by_id.get(int(r.instrument_id)),
                "side": r.side,
                "quantity": r.quantity,
                "target_weight": r.target_weight,
                "reason": r.reason,
                "status": r.status,
                "rank": r.rank,
                "predicted_return_20d": r.predicted_return_20d,
                "eligible_count": r.eligible_count,
                "decision_at": _dt(r.decision_at),
                "min_execution_date": r.min_execution_date.isoformat(),
                "execution_date": _date(r.execution_date),
                "decision_id": r.decision_id,
                "metadata": r.metadata_,
            }
            for r in rows
        ]


@router.get("/portfolios/{portfolio_id}/fills")
def get_shadow_fills(portfolio_id: int) -> list[dict]:
    with core_session() as session:
        rows = list(
            session.scalars(
                select(ShadowFill)
                .where(ShadowFill.portfolio_id == portfolio_id)
                .order_by(ShadowFill.id)
            )
        )
        return [
            {
                "id": r.id,
                "order_id": r.order_id,
                "ticker": r.ticker,
                "side": r.side,
                "quantity": r.quantity,
                "raw_open": r.raw_open,
                "fill_price": r.fill_price,
                "notional": r.notional,
                "commission": r.commission,
                "slippage_cost": r.slippage_cost,
                "execution_date": r.execution_date.isoformat(),
                "filled_at": _dt(r.filled_at),
                "decision_at": _dt(r.decision_at),
            }
            for r in rows
        ]


@router.get("/portfolios/{portfolio_id}/decisions")
def get_shadow_decisions(portfolio_id: int) -> list[dict]:
    with core_session() as session:
        rows = list(
            session.scalars(
                select(ShadowDecision)
                .where(ShadowDecision.portfolio_id == portfolio_id)
                .order_by(ShadowDecision.id)
            )
        )
        return [
            {
                "id": r.id,
                "forward_batch_id": r.forward_batch_id,
                "signal_as_of_date": r.signal_as_of_date.isoformat(),
                "signal_generated_at": _dt(r.signal_generated_at),
                "decision_at": _dt(r.decision_at),
                "iso_week": r.iso_week,
                "targets": r.targets,
                "risk_mode": r.risk_mode,
                "exposure_cap": r.exposure_cap,
                "policy_name": r.policy_name,
                "risk_name": r.risk_name,
                "metadata": r.metadata_,
            }
            for r in rows
        ]


@router.post("/init")
def init_shadow() -> dict[str, Any]:
    with core_session() as session:
        results = initialize_shadow_portfolios(session)
        session.commit()
        return {
            "kind": SHADOW_KIND,
            "portfolios": [
                {"id": r.portfolio_id, "name": r.name, "status": r.status, **r.summary} for r in results
            ],
        }


@router.post("/advance")
def enqueue_shadow_advance() -> dict[str, Any]:
    with core_session() as session:
        workflow = create_workflow(
            session,
            "AdvanceShadowPortfolio",
            "Advance Shadow Portfolio V0",
            ["Advance portfolios", "Finish"],
        )
        session.commit()
        wid = workflow.id
    async_result = worker_tasks.advance_shadow_portfolios.delay(wid)
    return {"workflow_id": wid, "task_id": async_result.id, "kind": SHADOW_KIND}
