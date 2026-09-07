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
from app.modules.shadow.application.pipeline_status import (
    AUTOMATION_DISABLED,
    READY_FOR_NEXT_SESSION,
    READY_NO_REBALANCE,
    WAITING_FOR_ANALYTICS,
    WAITING_FOR_FORWARD,
    WAITING_FOR_MARKET_COMPLETE,
    WAITING_FOR_TECHNICAL,
    build_pipeline_status,
    next_session_date_from_eod,
)
from app.modules.shadow.config import EXPERIMENT_GROUP, EXPERIMENT_GROUP_V2
from app.modules.shadow.infrastructure.models import (
    ShadowDecision,
    ShadowOrder,
    ShadowPortfolio,
    ShadowPortfolioSpec,
)

# Keep in sync with research_cycle.config.CYCLE_WORKFLOW_TYPE (avoid package import → catboost).
CYCLE_WORKFLOW_TYPE = "DAILY_RESEARCH_CYCLE_V0"

# Re-export readiness codes for existing tests / API consumers
CYCLE_RUNNING = "CYCLE_RUNNING"
CYCLE_STALE = "CYCLE_STALE"
PENDING_ORDERS_AWAITING_OPEN = "PENDING_ORDERS_AWAITING_OPEN"
ORDER_PLAN_PENDING = "ORDER_PLAN_PENDING"
BLOCKED_CONSISTENCY = "BLOCKED_CONSISTENCY"
NO_SHADOW_PORTFOLIOS = "NO_SHADOW_PORTFOLIOS"

# Catch-up / stage result codes
STAGE_SUCCESS = "SUCCESS"
STAGE_ALREADY_CURRENT = "ALREADY_CURRENT"
STAGE_WAITING_INPUT = "WAITING_INPUT"
STAGE_FAILED = "FAILED"
STAGE_DISABLED = "DISABLED"
STAGE_CYCLE_RUNNING = "CYCLE_RUNNING"


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
            Workflow.status.in_(("SUCCESS", "SUCCESS_NO_CHANGE", "NO_CHANGES")),
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


def _downstream_lags_complete_eod(wm: dict[str, Any], eod_date: Any) -> bool:
    if eod_date is None:
        return False
    analytics = wm.get("analytics_v2_latest_date")
    technical = wm.get("technical_v2_latest_date")
    forward = wm.get("forward_latest_as_of")
    market = wm.get("raw_market_latest_date")
    if market is not None and analytics is not None and market > analytics:
        return True
    if analytics is None or analytics < eod_date:
        return True
    if technical is None or technical < eod_date:
        return True
    if forward is None or forward < eod_date:
        return True
    return False


def _has_active_shadow(session: Session) -> bool:
    row = session.execute(
        select(ShadowPortfolio.id)
        .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
        .where(ShadowPortfolioSpec.experiment_group.in_([EXPERIMENT_GROUP, EXPERIMENT_GROUP_V2]))
        .limit(1)
    ).first()
    return row is not None


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

    cycle_covers = _cycle_covers_eod(last_ok, readiness.latest_complete_eod_date)
    pipeline = build_pipeline_status(
        session,
        readiness=readiness,
        wm=wm,
        running=running,
        stale=stale,
        pending_n=pending_n,
        cycle_covers=cycle_covers,
        consistency_blocked=bool(blockers),
        has_portfolios=bool(specs),
    )

    prep = pipeline.next_session_preparation_status
    ready_for_next = prep in (
        READY_FOR_NEXT_SESSION,
        READY_NO_REBALANCE,
        PENDING_ORDERS_AWAITING_OPEN,
    )
    blocker: str | None = None if ready_for_next and prep != PENDING_ORDERS_AWAITING_OPEN else prep
    if prep == PENDING_ORDERS_AWAITING_OPEN:
        blocker = PENDING_ORDERS_AWAITING_OPEN

    status_code = prep if not ready_for_next else (
        READY_FOR_NEXT_SESSION if prep == PENDING_ORDERS_AWAITING_OPEN else prep
    )

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
        "next_execution_session": next_session_date_from_eod(readiness.latest_complete_eod_date),
        "status_code": status_code,
        "blocker_code": blocker,
        "eod_readiness": readiness.to_dict(),
        "pipeline": pipeline.to_dict(),
        "current_session_status": pipeline.current_session_status,
        "next_session_preparation_status": pipeline.next_session_preparation_status,
        "mid_session_activation": pipeline.mid_session_activation,
        "today_summary": pipeline.today_summary,
        "next_session_summary": pipeline.next_session_summary,
        "automation": {
            "research_live_mode": bool(settings.research_live_mode),
            "daily_research_cycle_enabled": bool(settings.daily_research_cycle_enabled),
            "daily_research_cycle_hour": settings.daily_research_cycle_hour,
            "daily_research_cycle_minute": settings.daily_research_cycle_minute,
            "eod_readiness_retry_enabled": bool(settings.eod_readiness_retry_enabled),
            "eod_readiness_retry_minutes": int(settings.eod_readiness_retry_minutes or 15),
            "intraday_market_enabled": bool(settings.intraday_market_enabled),
            "warning": pipeline.automation_warning,
        },
        "last_eod_cycle": {
            "workflow_id": last_ok.id if last_ok else None,
            "status": last_ok.status if last_ok else None,
            "finished_at": (
                (last_ok.finished_at or last_ok.updated_at).isoformat()
                if last_ok and (last_ok.finished_at or last_ok.updated_at)
                else None
            ),
            "covers_latest_eod": cycle_covers,
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
                "activated_at": p.activated_at.isoformat() if p.activated_at else None,
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
            "relations_v2_latest_as_of": (
                wm.get("relations_v2_latest_as_of").isoformat()
                if wm.get("relations_v2_latest_as_of")
                else None
            ),
            "forward_latest_as_of": (
                wm.get("forward_latest_as_of").isoformat() if wm.get("forward_latest_as_of") else None
            ),
            "shadow_plan_latest_as_of": pipeline.watermarks.get("shadow_plan"),
        },
    }


def maybe_trigger_cycle_if_ready(session: Session) -> dict[str, Any]:
    """Catch-up poll: trigger Daily Research Cycle once when market ahead of analytics.

    Does NOT require Analytics to already be current (that was the live bug:
    WAITING_FOR_ANALYTICS never self-healed). Never runs the full cycle inline.
    Idempotent via lock + ALREADY_CURRENT / CYCLE_RUNNING.
    """
    settings = get_settings()
    if not settings.eod_readiness_retry_enabled:
        return {
            "status": STAGE_DISABLED,
            "stage": STAGE_DISABLED,
            "reason": "EOD_READINESS_RETRY_ENABLED=false (set RESEARCH_LIVE_MODE=true)",
        }

    readiness = evaluate_eod_readiness(session)
    wm = _collect_watermarks(session)
    eod = readiness.latest_complete_eod_date

    if eod is None and not readiness.ready:
        return {
            "status": STAGE_WAITING_INPUT,
            "stage": STAGE_WAITING_INPUT,
            "blocker_code": readiness.blocker_code or WAITING_FOR_MARKET_COMPLETE,
            "readiness": readiness.to_dict(),
        }

    last_ok = _last_successful_cycle(session)
    lags = _downstream_lags_complete_eod(wm, eod)
    covers = _cycle_covers_eod(last_ok, eod)

    if readiness.ready and covers and not lags:
        return {
            "status": STAGE_ALREADY_CURRENT,
            "stage": STAGE_ALREADY_CURRENT,
            "readiness": readiness.to_dict(),
        }

    # Catch-up path: complete EOD exists but analytics/technical/forward behind,
    # OR cycle does not cover latest complete EOD yet.
    if not readiness.ready and readiness.blocker_code == WAITING_FOR_MARKET_COMPLETE:
        return {
            "status": STAGE_WAITING_INPUT,
            "stage": STAGE_WAITING_INPUT,
            "blocker_code": WAITING_FOR_MARKET_COMPLETE,
            "readiness": readiness.to_dict(),
        }

    if not lags and covers:
        return {
            "status": STAGE_ALREADY_CURRENT,
            "stage": STAGE_ALREADY_CURRENT,
            "readiness": readiness.to_dict(),
        }

    latest = _latest_cycle_workflow(session)
    if latest is not None and str(latest.status).upper() == "RUNNING":
        return {
            "status": STAGE_CYCLE_RUNNING,
            "stage": STAGE_ALREADY_CURRENT,
            "workflow_id": latest.id,
        }

    try:
        from app.worker import tasks as worker_tasks

        async_result = worker_tasks.daily_research_cycle.delay(None)
        return {
            "status": STAGE_SUCCESS,
            "stage": STAGE_SUCCESS,
            "triggered": True,
            "task_id": async_result.id,
            "reason": "downstream_lag_or_cycle_gap",
            "readiness": readiness.to_dict(),
            "watermarks": {
                "market": wm.get("raw_market_latest_date").isoformat()
                if wm.get("raw_market_latest_date")
                else None,
                "analytics": wm.get("analytics_v2_latest_date").isoformat()
                if wm.get("analytics_v2_latest_date")
                else None,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": STAGE_FAILED,
            "stage": STAGE_FAILED,
            "error": str(exc)[:500],
            "readiness": readiness.to_dict(),
        }


def maybe_startup_catchup(session: Session) -> dict[str, Any]:
    """Backend/worker startup: if active Shadow exists and downstream lags, trigger once."""
    settings = get_settings()
    if not (settings.research_live_mode or settings.eod_readiness_retry_enabled):
        return {
            "status": STAGE_DISABLED,
            "stage": STAGE_DISABLED,
            "reason": "automation_off",
        }
    if not _has_active_shadow(session):
        return {
            "status": STAGE_ALREADY_CURRENT,
            "stage": STAGE_ALREADY_CURRENT,
            "reason": "no_active_shadow",
        }
    return maybe_trigger_cycle_if_ready(session)


__all__ = [
    "AUTOMATION_DISABLED",
    "BLOCKED_CONSISTENCY",
    "CYCLE_RUNNING",
    "CYCLE_STALE",
    "NO_SHADOW_PORTFOLIOS",
    "ORDER_PLAN_PENDING",
    "PENDING_ORDERS_AWAITING_OPEN",
    "READY_FOR_NEXT_SESSION",
    "READY_NO_REBALANCE",
    "STAGE_ALREADY_CURRENT",
    "STAGE_DISABLED",
    "STAGE_FAILED",
    "STAGE_SUCCESS",
    "STAGE_WAITING_INPUT",
    "WAITING_FOR_ANALYTICS",
    "WAITING_FOR_FORWARD",
    "WAITING_FOR_MARKET_COMPLETE",
    "WAITING_FOR_TECHNICAL",
    "EodReadiness",
    "build_daily_operations_status",
    "evaluate_eod_readiness",
    "maybe_startup_catchup",
    "maybe_trigger_cycle_if_ready",
]
