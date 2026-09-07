"""Read-only Shadow Portfolio V0 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import get_settings
from app.infrastructure.db.session import core_session
from app.infrastructure.market.models import Instrument
from app.modules.market.application.intraday_cache import IntradayQuoteCache
from app.modules.market.application.workflows import create_workflow
from app.modules.shadow.application.daily_operations import build_daily_operations_status
from app.modules.shadow.application.intraday_universe import resolve_intraday_universe
from app.modules.shadow.application.live_valuation import build_live_portfolio_snapshot
from app.modules.shadow.application.lot_aware import is_lot_aware_spec
from app.modules.shadow.application.service import initialize_shadow_portfolios
from app.modules.shadow.config import (
    SHADOW_KIND,
    operational_shadow_configs,
    realism_v2_shadow_configs,
)
from app.modules.shadow.domain.open_execution import POLICY_NAME, can_fill_with_session_open
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


def _pending_reason_for_order(
    order: ShadowOrder,
    quote: Any,
    *,
    cash: float | None = None,
    commission_bps: float = 0.0,
) -> dict[str, Any]:
    base = {
        "order_id": int(order.id),
        "ticker": order.ticker,
        "side": order.side,
        "min_execution_date": order.min_execution_date.isoformat(),
        "created_at": _dt(order.created_at),
    }
    if quote is None:
        return {**base, "reason": "QUOTE_UNAVAILABLE", "session_date": None}
    session_date = quote.trading_date
    if session_date is None:
        return {**base, "reason": "OPEN_PRICE_NOT_AVAILABLE", "session_date": None}
    elig = can_fill_with_session_open(
        order_created_at=order.created_at,
        min_execution_date=order.min_execution_date,
        session_date=session_date,
        open_price=quote.open_price,
        market_status=quote.market_status,
        quote_freshness=quote.freshness,
        observed_at=quote.observed_at,
    )
    reason = elig.reason if not elig.eligible else "ELIGIBLE"
    if (
        elig.eligible
        and order.side == "BUY"
        and cash is not None
        and quote.open_price is not None
        and float(order.quantity) > 0
    ):
        raw = float(quote.open_price)
        notional = float(order.quantity) * raw
        commission = notional * (float(commission_bps) / 10_000.0)
        if notional + commission > float(cash) + 1e-6:
            reason = "INSUFFICIENT_CASH"
    return {
        **base,
        "reason": reason,
        "session_date": session_date.isoformat(),
        "delayed_observation": elig.delayed_observation,
        "open_price": quote.open_price,
        "quote_freshness": str(quote.freshness),
        "market_status": str(quote.market_status),
    }


def _live_enrichment(session: Any, portfolio: ShadowPortfolio) -> dict[str, Any]:
    settings = get_settings()
    cache = IntradayQuoteCache()
    last = cache.get_last_refresh()
    members = resolve_intraday_universe(session)
    positions = portfolio.positions or {}
    needed_ids: set[int] = set()
    if isinstance(positions, dict):
        for key, row in positions.items():
            if isinstance(row, dict) and abs(float(row.get("quantity") or 0)) > 1e-12:
                needed_ids.add(int(row.get("instrument_id") or key))
    pending_orders = list(
        session.scalars(
            select(ShadowOrder).where(
                ShadowOrder.portfolio_id == portfolio.id,
                ShadowOrder.status == "PENDING",
            )
        )
    )
    for order in pending_orders:
        needed_ids.add(int(order.instrument_id))

    quotes_by_instrument: dict[int, Any] = {}
    for m in members:
        if m.instrument_id not in needed_ids:
            continue
        q = cache.get(m.board, m.secid)
        if q is not None:
            quotes_by_instrument[m.instrument_id] = q

    fills = list(
        session.scalars(
            select(ShadowFill).where(ShadowFill.portfolio_id == portfolio.id)
        )
    )
    # Prefer position JSON avg_entry / cost_basis when present (V2); else fills.
    entry_by_instrument: dict[int, float] = {}
    realized_total = 0.0
    if isinstance(positions, dict):
        for key, row in positions.items():
            if not isinstance(row, dict):
                continue
            iid = int(row.get("instrument_id") or key)
            if row.get("avg_entry") is not None:
                entry_by_instrument[iid] = float(row["avg_entry"])
            if row.get("realized_pnl") is not None:
                realized_total += float(row["realized_pnl"])
    if not entry_by_instrument:
        buy_qty: dict[int, float] = {}
        buy_notional: dict[int, float] = {}
        for fill in fills:
            if fill.side != "BUY":
                continue
            iid = int(fill.instrument_id)
            buy_qty[iid] = buy_qty.get(iid, 0.0) + float(fill.quantity)
            buy_notional[iid] = buy_notional.get(iid, 0.0) + float(fill.fill_price) * float(
                fill.quantity
            )
        entry_by_instrument = {
            iid: (buy_notional[iid] / qty) for iid, qty in buy_qty.items() if qty > 1e-12
        }

    fees_total = sum(float(f.commission or 0) for f in fills)

    spec = session.get(ShadowPortfolioSpec, portfolio.spec_id)
    cost_basis_nav = float(spec.initial_capital) if spec is not None else None

    snapshot = build_live_portfolio_snapshot(
        portfolio_id=int(portfolio.id),
        cash=float(portfolio.cash),
        positions=positions if isinstance(positions, dict) else {},
        quotes_by_instrument=quotes_by_instrument,
        entry_by_instrument=entry_by_instrument,
        cost_basis_nav=cost_basis_nav,
    )
    pending_reasons = [
        _pending_reason_for_order(
            o,
            quotes_by_instrument.get(int(o.instrument_id)),
            cash=float(portfolio.cash),
            commission_bps=float(spec.commission_bps) if spec is not None else 0.0,
        )
        for o in pending_orders
    ]
    latest_decision = session.scalar(
        select(ShadowDecision)
        .where(ShadowDecision.portfolio_id == portfolio.id)
        .order_by(ShadowDecision.id.desc())
        .limit(1)
    )
    order_plan = None
    skipped = None
    if latest_decision is not None:
        dmeta = latest_decision.metadata_ or {}
        order_plan = dmeta.get("order_plan")
        skipped = dmeta.get("skipped")

    live_positions = []
    for m in snapshot.position_marks:
        pos_row = (positions or {}).get(str(m.instrument_id)) or {}
        live_positions.append(
            {
                "instrument_id": m.instrument_id,
                "ticker": m.ticker,
                "quantity": m.quantity,
                "lots": pos_row.get("lots"),
                "lot_size": pos_row.get("lot_size"),
                "avg_entry": pos_row.get("avg_entry", m.entry_price),
                "cost_basis": pos_row.get("cost_basis", m.invested_cost),
                "realized_pnl": pos_row.get("realized_pnl"),
                "entry_price": m.entry_price,
                "mark_price": m.mark_price,
                "mark_source": m.mark_source,
                "market_value": m.market_value,
                "invested_cost": m.invested_cost,
                "unrealized_pnl": m.unrealized_pnl,
                "unrealized_pnl_pct": m.unrealized_pnl_pct,
                "change_pct": m.unrealized_pnl_pct,
                "freshness": m.freshness,
                "quote_time": m.quote_time.isoformat() if m.quote_time else None,
            }
        )

    return {
        "intraday_enabled": bool(settings.intraday_market_enabled),
        "open_execution_policy": POLICY_NAME,
        "last_intraday_refresh": last,
        "lot_aware": is_lot_aware_spec(spec) if spec is not None else False,
        "execution_version": (spec.payload or {}).get("execution_version") if spec else None,
        "order_plan": order_plan,
        "skipped": skipped,
        "cash_breakdown": {
            "cash": snapshot.cash,
            "invested_cost": snapshot.invested_cost,
            "market_value": snapshot.market_value,
            "nav": snapshot.nav,
            "fees_paid": fees_total,
            "realized_pnl": realized_total,
            "unrealized_pnl": snapshot.unrealized_pnl,
        },
        "live": {
            "cash": snapshot.cash,
            "invested_cost": snapshot.invested_cost,
            "market_value": snapshot.market_value,
            "nav": snapshot.nav,
            "unrealized_pnl": snapshot.unrealized_pnl,
            "unrealized_pnl_pct": snapshot.unrealized_pnl_pct,
            "realized_pnl": realized_total,
            "fees_paid": fees_total,
            "quote_coverage": snapshot.quote_coverage,
            "warnings": list(snapshot.warnings),
            "as_of": snapshot.as_of.isoformat() if snapshot.as_of else None,
            "positions": live_positions,
        },
        "pending_order_reasons": pending_reasons,
    }


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
        "fractional_shares": bool(spec.fractional_shares),
        "lot_aware": is_lot_aware_spec(spec),
        "execution_version": (spec.payload or {}).get("execution_version"),
        "version": spec.version,
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
    fractional_shares: bool = True
    lot_aware: bool = False
    execution_version: str | None = None
    version: str | None = None


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
            summary.update(_live_enrichment(session, portfolio))
            live = summary.get("live") or {}
            if live.get("quote_coverage", 0) > 0 and live.get("nav") is not None:
                summary["live_nav"] = live["nav"]
                summary["live_market_value"] = live["market_value"]
            portfolios.append(summary)
            if activated_at is None or (
                portfolio.activated_at and portfolio.activated_at < activated_at
            ):
                activated_at = portfolio.activated_at
            experiment_group = experiment_group or spec.experiment_group

        settings = get_settings()
        cache = IntradayQuoteCache()
        return {
            "kind": SHADOW_KIND,
            "experiment_group": experiment_group,
            "activated_at": _dt(activated_at),
            "automatic_schedule": "not_configured",
            "intraday": {
                "enabled": bool(settings.intraday_market_enabled),
                "policy": POLICY_NAME,
                "last_refresh": cache.get_last_refresh(),
                "refresh_minutes": int(settings.intraday_refresh_minutes),
            },
            "portfolios": portfolios,
        }


@router.get("/live")
def shadow_live() -> dict[str, Any]:
    """Ephemeral live marks + pending open-execution reasons (no durable NAV write)."""
    with core_session() as session:
        rows = session.execute(
            select(ShadowPortfolio, ShadowPortfolioSpec)
            .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
            .order_by(ShadowPortfolio.id)
        ).all()
        portfolios: list[dict[str, Any]] = []
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
            summary = _portfolio_summary(portfolio, spec, pending=pending, fills=fills)
            summary.update(_live_enrichment(session, portfolio))
            portfolios.append(summary)
        settings = get_settings()
        cache = IntradayQuoteCache()
        return {
            "kind": SHADOW_KIND,
            "intraday_enabled": bool(settings.intraday_market_enabled),
            "open_execution_policy": POLICY_NAME,
            "last_intraday_refresh": cache.get_last_refresh(),
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


@router.get("/daily-operations")
@router.get("/operations/status")
def shadow_daily_operations() -> dict[str, Any]:
    """EOD readiness, pending orders, automation flags, consistency blockers."""
    with core_session() as session:
        return build_daily_operations_status(session)


@router.get("/portfolios/{portfolio_id}/current")
def get_shadow_portfolio_current(portfolio_id: int) -> dict[str, Any]:
    """Current portfolio snapshot for UI: lots, cash breakdown, order_plan, live marks."""
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
        live = _live_enrichment(session, portfolio)
        readiness = build_daily_operations_status(session)
        summary.update(
            {
                "positions": portfolio.positions,
                "provenance": portfolio.provenance,
                "warnings": portfolio.warnings,
                "config_hash": spec.config_hash,
                "candidate_config_hash": spec.candidate_config_hash,
                "candidate_name": spec.candidate_name,
                "candidate_version": spec.candidate_version,
                "readiness": {
                    "ready_for_next_session": readiness.get("ready_for_next_session"),
                    "blocker_code": readiness.get("blocker_code"),
                    "status_code": readiness.get("status_code"),
                    "latest_complete_eod_date": readiness.get("latest_complete_eod_date"),
                    "pending_orders": readiness.get("pending_orders"),
                },
            }
        )
        summary.update(live)
        return summary


@router.post("/init")
def init_shadow(
    group: Annotated[str, Query(description="operational | realism-v2")] = "operational",
) -> dict[str, Any]:
    if group not in ("operational", "realism-v2"):
        raise HTTPException(400, "group must be operational or realism-v2")
    configs = (
        list(realism_v2_shadow_configs()) if group == "realism-v2" else list(operational_shadow_configs())
    )
    with core_session() as session:
        results = initialize_shadow_portfolios(session, configs=configs)
        session.commit()
        return {
            "kind": SHADOW_KIND,
            "group": group,
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
