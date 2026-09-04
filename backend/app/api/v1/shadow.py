"""Read-only Shadow Portfolio V0 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.infrastructure.db.session import core_session
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


class ShadowPortfolioSummary(BaseModel):
    id: str
    name: str
    status: str
    policy_name: str
    risk_name: str
    activated_at: str | None
    cash: float
    risk_mode: str
    exposure_cap: float
    pending_orders: int
    fills: int
    last_processed_market_date: str | None
    kind: str = SHADOW_KIND


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
            pending = session.scalars(
                select(ShadowOrder).where(
                    ShadowOrder.portfolio_id == portfolio.id, ShadowOrder.status == "PENDING"
                )
            ).all()
            fills = session.scalars(
                select(ShadowFill).where(ShadowFill.portfolio_id == portfolio.id)
            ).all()
            out.append(
                ShadowPortfolioSummary(
                    id=str(portfolio.id),
                    name=spec.name,
                    status=portfolio.status,
                    policy_name=spec.policy_name,
                    risk_name=spec.risk_name,
                    activated_at=_dt(portfolio.activated_at),
                    cash=float(portfolio.cash),
                    risk_mode=portfolio.risk_mode,
                    exposure_cap=float(portfolio.exposure_cap),
                    pending_orders=len(pending),
                    fills=len(fills),
                    last_processed_market_date=_dt(portfolio.last_processed_market_date),
                )
            )
        return out


@router.get("/portfolios/{portfolio_id}")
def get_shadow_portfolio(portfolio_id: int) -> dict[str, Any]:
    with core_session() as session:
        portfolio = session.get(ShadowPortfolio, portfolio_id)
        if portfolio is None:
            raise HTTPException(404, "Shadow portfolio not found")
        spec = session.get(ShadowPortfolioSpec, portfolio.spec_id)
        assert spec is not None
        return {
            "id": str(portfolio.id),
            "name": spec.name,
            "status": portfolio.status,
            "activated_at": _dt(portfolio.activated_at),
            "first_forward_batch_id": portfolio.first_forward_batch_id,
            "first_forward_as_of_date": _dt(portfolio.first_forward_as_of_date),
            "cash": portfolio.cash,
            "positions": portfolio.positions,
            "risk_mode": portfolio.risk_mode,
            "exposure_cap": portfolio.exposure_cap,
            "last_processed_market_date": _dt(portfolio.last_processed_market_date),
            "last_decision_iso_week": portfolio.last_decision_iso_week,
            "policy_name": spec.policy_name,
            "risk_name": spec.risk_name,
            "provenance": portfolio.provenance,
            "kind": SHADOW_KIND,
        }


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
                "position_count": r.position_count,
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
        return [
            {
                "id": r.id,
                "ticker": r.ticker,
                "side": r.side,
                "quantity": r.quantity,
                "target_weight": r.target_weight,
                "reason": r.reason,
                "status": r.status,
                "rank": r.rank,
                "predicted_return_20d": r.predicted_return_20d,
                "decision_at": _dt(r.decision_at),
                "min_execution_date": r.min_execution_date.isoformat(),
                "execution_date": _dt(r.execution_date),
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
                "execution_date": r.execution_date.isoformat(),
                "filled_at": _dt(r.filled_at),
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
