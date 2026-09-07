"""Shadow daily operations / EOD readiness status (no full cycle every poll)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.market.models import Workflow
from app.modules.market.application.intraday_cache import IntradayQuoteCache
from app.modules.prediction.application.forward_readiness import select_latest_complete_as_of
from app.modules.shadow.application.consistency import check_shadow_consistency
from app.modules.shadow.application.lot_aware import is_lot_aware_spec
from app.modules.shadow.config import EXPERIMENT_GROUP, EXPERIMENT_GROUP_V2
from app.modules.shadow.infrastructure.models import (
    ShadowDecision,
    ShadowOrder,
    ShadowPortfolio,
    ShadowPortfolioSpec,
)

# Keep in sync with research_cycle.config.CYCLE_WORKFLOW_TYPE (avoid package import → catboost).
CYCLE_WORKFLOW_TYPE = "DAILY_RESEARCH_CYCLE_V0"

# Task §69-style readiness / blocker codes
READY_FOR_NEXT_SESSION = "READY_FOR_NEXT_SESSION"
WAITING_FOR_MARKET_COMPLETE = "WAITING_FOR_MARKET_COMPLETE"
WAITING_FOR_ANALYTICS = "WAITING_FOR_ANALYTICS"
WAITING_FOR_TECHNICAL = "WAITING_FOR_TECHNICAL"
WAITING_FOR_FORWARD = "WAITING_FOR_FORWARD"
CYCLE_RUNNING = "CYCLE_RUNNING"
CYCLE_STALE = "CYCLE_STALE"
PENDING_ORDERS_AWAITING_OPEN = "PENDING_ORDERS_AWAITING_OPEN"
ORDER_PLAN_PENDING = "ORDER_PLAN_PENDING"
BLOCKED_CONSISTENCY = "BLOCKED_CONSISTENCY"
NO_SHADOW_PORTFOLIOS = "NO_SHADOW_PORTFOLIOS"


@dataclass(frozen=True, slots=True)
class EodReadiness:
    ready: bool
    blocker_code: str | None
    latest_complete_eod_date: Any
    reason: str
    completeness: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "blocker_code": self.blocker_code,
            "latest_complete_eod_date": (
                self.latest_complete_eod_date.isoformat()
                if self.latest_complete_eod_date is not None
                and hasattr(self.latest_complete_eod_date, "isoformat")
                else self.latest_complete_eod_date
            ),
            "reason": self.reason,
            "completeness": self.completeness,
        }


def _collect_watermarks(session: Session) -> dict[str, Any]:
    from app.modules.research_cycle.watermarks import collect_watermarks

    return collect_watermarks(session)


def _latest_cycle_workflow(session: Session) -> Workflow | None:
    from app.modules.research_cycle.watermarks import latest_cycle_workflow

    return latest_cycle_workflow(session)


def evaluate_eod_readiness(session: Session) -> EodReadiness:
    """Completeness-threshold gate using existing Forward readiness watermarks."""
    report = select_latest_complete_as_of(session)
    completeness = report.to_dict()
    wm = _collect_watermarks(session)
    market = wm.get("raw_market_latest_date")
    analytics = wm.get("analytics_v2_latest_date")
    technical = wm.get("technical_v2_latest_date")

    if not report.complete or report.as_of is None:
        return EodReadiness(
            ready=False,
            blocker_code=WAITING_FOR_MARKET_COMPLETE,
            latest_complete_eod_date=report.as_of or market,
            reason=report.reason or "market_incomplete",
            completeness=completeness,
        )
    if analytics is None or analytics < report.as_of:
        return EodReadiness(
            ready=False,
            blocker_code=WAITING_FOR_ANALYTICS,
            latest_complete_eod_date=report.as_of,
            reason="analytics_behind_complete_eod",
            completeness=completeness,
        )
    if technical is None or technical < report.as_of:
        return EodReadiness(
            ready=False,
            blocker_code=WAITING_FOR_TECHNICAL,
            latest_complete_eod_date=report.as_of,
            reason="technical_behind_complete_eod",
            completeness=completeness,
        )
    return EodReadiness(
        ready=True,
        blocker_code=None,
        latest_complete_eod_date=report.as_of,
        reason="eod_complete",
        completeness=completeness,
    )


def _last_successful_cycle(session: Session) -> Workflow | None:
    return session.scalar(
        select(Workflow)
        .where(
            Workflow.workflow_type == CYCLE_WORKFLOW_TYPE,
            Workflow.status.in_(("SUCCESS", "SUCCESS_NO_CHANGE")),
        )
        .order_by(Workflow.id.desc())
        .limit(1)
    )


def _cycle_covers_eod(workflow: Workflow | None, eod_date: Any) -> bool:
    if workflow is None or eod_date is None:
        return False
    meta = workflow.meta or {}
    after = meta.get("market_watermark_after") or (meta.get("watermarks_after") or {}).get(
        "raw_market_latest_date"
    )
    if after is None:
        finished = workflow.finished_at or workflow.updated_at
        if finished is None:
            return False
        return finished.date() >= eod_date if hasattr(eod_date, "year") else False
    try:
        from datetime import date as date_cls

        after_d = date_cls.fromisoformat(str(after)[:10])
        return after_d >= eod_date
    except ValueError:
        return False


def build_daily_operations_status(session: Session) -> dict[str, Any]:
    settings = get_settings()
    readiness = evaluate_eod_readiness(session)
    wm = _collect_watermarks(session)
    latest = _latest_cycle_workflow(session)
    last_ok = _last_successful_cycle(session)
    cache = IntradayQuoteCache()
    last_intraday = cache.get_last_refresh()

    running = latest is not None and str(latest.status).upper() == "RUNNING"
    pending_n = int(
        session.scalar(select(func.count()).select_from(ShadowOrder).where(ShadowOrder.status == "PENDING"))
        or 0
    )

    specs = list(
        session.execute(
            select(ShadowPortfolio, ShadowPortfolioSpec)
            .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
            .where(ShadowPortfolioSpec.experiment_group.in_([EXPERIMENT_GROUP, EXPERIMENT_GROUP_V2]))
            .order_by(ShadowPortfolio.id)
        ).all()
    )

    consistency = check_shadow_consistency(session, portfolio_ids=[p.id for p, _ in specs])
    blockers = [i for i in consistency if i.severity == "BLOCKER"]

    order_plan_status = "NONE"
    latest_decision = session.scalar(select(ShadowDecision).order_by(ShadowDecision.id.desc()).limit(1))
    if latest_decision is not None:
        meta = latest_decision.metadata_ or {}
        if meta.get("order_plan"):
            order_plan_status = "PRESENT"
        elif pending_n > 0:
            order_plan_status = "ORDERS_WITHOUT_PLAN_META"

    stale = False
    last_ok_at = None
    if last_ok is not None:
        last_ok_at = last_ok.finished_at or last_ok.updated_at
        if last_ok_at is not None and last_ok_at.tzinfo is None:
            last_ok_at = last_ok_at.replace(tzinfo=UTC)
        if last_ok_at is not None and datetime.now(UTC) - last_ok_at > timedelta(hours=36):
            if readiness.ready and not _cycle_covers_eod(last_ok, readiness.latest_complete_eod_date):
                stale = True

    ready_for_next = False
    blocker: str | None = None
    if not specs:
        blocker = NO_SHADOW_PORTFOLIOS
    elif blockers:
        blocker = BLOCKED_CONSISTENCY
    elif running:
        blocker = CYCLE_RUNNING
    elif stale:
        blocker = CYCLE_STALE
    elif not readiness.ready:
        blocker = readiness.blocker_code
    elif not _cycle_covers_eod(last_ok, readiness.latest_complete_eod_date):
        blocker = WAITING_FOR_FORWARD if wm.get("forward_latest_as_of") is None else ORDER_PLAN_PENDING
    elif pending_n > 0:
        blocker = PENDING_ORDERS_AWAITING_OPEN
        ready_for_next = True
    else:
        ready_for_next = True
        blocker = None

    status_code = (
        READY_FOR_NEXT_SESSION
        if ready_for_next and blocker in (None, PENDING_ORDERS_AWAITING_OPEN)
        else (blocker or "UNKNOWN")
    )

    next_session = None
    if readiness.latest_complete_eod_date is not None:
        next_session = (readiness.latest_complete_eod_date + timedelta(days=1)).isoformat()

    return {
        "latest_complete_eod_date": readiness.to_dict()["latest_complete_eod_date"],
        "latest_forward_as_of": (
            wm.get("forward_latest_as_of").isoformat()
            if wm.get("forward_latest_as_of") is not None
            else None
        ),
        "order_plan_status": order_plan_status,
        "pending_orders": pending_n,
        "ready_for_next_session": ready_for_next,
        "next_execution_session": next_session,
        "status_code": status_code,
        "blocker_code": blocker if not ready_for_next or blocker == PENDING_ORDERS_AWAITING_OPEN else None,
        "eod_readiness": readiness.to_dict(),
        "automation": {
            "daily_research_cycle_enabled": bool(settings.daily_research_cycle_enabled),
            "daily_research_cycle_hour": settings.daily_research_cycle_hour,
            "daily_research_cycle_minute": settings.daily_research_cycle_minute,
            "eod_readiness_retry_enabled": bool(
                getattr(settings, "eod_readiness_retry_enabled", False)
            ),
            "eod_readiness_retry_minutes": int(
                getattr(settings, "eod_readiness_retry_minutes", 15) or 15
            ),
            "intraday_market_enabled": bool(settings.intraday_market_enabled),
        },
        "last_eod_cycle": {
            "workflow_id": last_ok.id if last_ok else None,
            "status": last_ok.status if last_ok else None,
            "finished_at": (
                (last_ok.finished_at or last_ok.updated_at).isoformat()
                if last_ok and (last_ok.finished_at or last_ok.updated_at)
                else None
            ),
            "covers_latest_eod": _cycle_covers_eod(last_ok, readiness.latest_complete_eod_date),
            "stale": stale,
        },
        "last_intraday_refresh": last_intraday,
        "consistency": [i.to_dict() for i in consistency],
        "portfolios": [
            {
                "id": p.id,
                "name": s.name,
                "experiment_group": s.experiment_group,
                "status": p.status,
                "lot_aware": is_lot_aware_spec(s),
                "fractional_shares": bool(s.fractional_shares),
                "cash": float(p.cash),
                "last_processed_market_date": (
                    p.last_processed_market_date.isoformat() if p.last_processed_market_date else None
                ),
            }
            for p, s in specs
        ],
        "watermarks": {
            "raw_market_latest_date": (
                wm.get("raw_market_latest_date").isoformat()
                if wm.get("raw_market_latest_date")
                else None
            ),
            "analytics_v2_latest_date": (
                wm.get("analytics_v2_latest_date").isoformat()
                if wm.get("analytics_v2_latest_date")
                else None
            ),
            "technical_v2_latest_date": (
                wm.get("technical_v2_latest_date").isoformat()
                if wm.get("technical_v2_latest_date")
                else None
            ),
            "forward_latest_as_of": (
                wm.get("forward_latest_as_of").isoformat() if wm.get("forward_latest_as_of") else None
            ),
        },
    }


def maybe_trigger_cycle_if_ready(session: Session) -> dict[str, Any]:
    """Lightweight readiness poll: trigger Daily Research Cycle once when EOD ready."""
    settings = get_settings()
    if not getattr(settings, "eod_readiness_retry_enabled", False):
        return {"status": "DISABLED", "reason": "EOD_READINESS_RETRY_ENABLED=false"}
    readiness = evaluate_eod_readiness(session)
    if not readiness.ready:
        return {"status": "WAITING", "readiness": readiness.to_dict()}
    last_ok = _last_successful_cycle(session)
    if _cycle_covers_eod(last_ok, readiness.latest_complete_eod_date):
        return {"status": "ALREADY_COVERED", "readiness": readiness.to_dict()}
    latest = _latest_cycle_workflow(session)
    if latest is not None and str(latest.status).upper() == "RUNNING":
        return {"status": "CYCLE_RUNNING", "workflow_id": latest.id}
    from app.worker import tasks as worker_tasks

    async_result = worker_tasks.daily_research_cycle.delay(None)
    return {
        "status": "TRIGGERED",
        "task_id": async_result.id,
        "readiness": readiness.to_dict(),
    }
