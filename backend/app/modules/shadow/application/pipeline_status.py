"""Unified Daily Decision Pipeline status (current session vs next-session prep)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.shadow.config import EXPERIMENT_GROUP, EXPERIMENT_GROUP_V2
from app.modules.shadow.domain.open_execution import (
    ensure_aware_utc,
    session_open_time_utc,
)
from app.modules.shadow.infrastructure.models import (
    ShadowDecision,
    ShadowOrder,
    ShadowPortfolio,
    ShadowPortfolioSpec,
)

# Current session (fills / marks today)
CURRENT_NO_ACTIVITY = "NO_ACTIVITY"
CURRENT_PENDING_AWAITING_OPEN = "PENDING_ORDERS_AWAITING_OPEN"
CURRENT_MID_SESSION_WAIT = "MID_SESSION_ACTIVATION_WAIT_NEXT_OPEN"
CURRENT_SESSION_ACTIVE = "SESSION_ACTIVE"
CURRENT_FILLS_BLOCKED_AFTER_OPEN = "FILLS_BLOCKED_ORDER_AFTER_OPEN"

# Next-session preparation (EOD → Forward → plan)
READY_FOR_NEXT_SESSION = "READY_FOR_NEXT_SESSION"
READY_NO_REBALANCE = "READY_NO_REBALANCE"
WAITING_FOR_MARKET_COMPLETE = "WAITING_FOR_MARKET_COMPLETE"
WAITING_FOR_ANALYTICS = "WAITING_FOR_ANALYTICS"
WAITING_FOR_TECHNICAL = "WAITING_FOR_TECHNICAL"
WAITING_FOR_RELATIONS = "WAITING_FOR_RELATIONS"
WAITING_FOR_FORWARD = "WAITING_FOR_FORWARD"
WAITING_FOR_SHADOW_PLAN = "WAITING_FOR_SHADOW_PLAN"
CYCLE_RUNNING = "CYCLE_RUNNING"
CYCLE_STALE = "CYCLE_STALE"
AUTOMATION_DISABLED = "AUTOMATION_DISABLED"
BLOCKED_CONSISTENCY = "BLOCKED_CONSISTENCY"
NO_SHADOW_PORTFOLIOS = "NO_SHADOW_PORTFOLIOS"
PENDING_ORDERS_AWAITING_OPEN = "PENDING_ORDERS_AWAITING_OPEN"
ORDER_PLAN_PENDING = "ORDER_PLAN_PENDING"

_SUMMARY_RU = {
    CURRENT_NO_ACTIVITY: "Сегодня нет активных ордеров на исполнение.",
    CURRENT_PENDING_AWAITING_OPEN: "Есть PENDING-ордера — ждут официальный OPEN следующей сессии.",
    CURRENT_MID_SESSION_WAIT: (
        "Эксперимент/ордера созданы после OPEN текущей сессии — исполнение только со следующего OPEN."
    ),
    CURRENT_SESSION_ACTIVE: "Сессия активна; ожидаются/выполняются fills по правилам OPEN.",
    CURRENT_FILLS_BLOCKED_AFTER_OPEN: "Ордера после OPEN — сегодняшний OPEN не используется (prospective guard).",
    READY_FOR_NEXT_SESSION: "Подготовка к следующей сессии завершена.",
    READY_NO_REBALANCE: "Контур готов; ребаланс не требуется (нет новых ордеров).",
    WAITING_FOR_MARKET_COMPLETE: "Ждём полный EOD по рынку.",
    WAITING_FOR_ANALYTICS: "Рынок готов, Analytics отстаёт — нужен catch-up Daily Research Cycle.",
    WAITING_FOR_TECHNICAL: "Analytics готов, Technical отстаёт.",
    WAITING_FOR_RELATIONS: "Relations snapshot устарел относительно сигнала.",
    WAITING_FOR_FORWARD: "Ждём Forward-сигнал на актуальный EOD.",
    WAITING_FOR_SHADOW_PLAN: "Ждём Shadow order plan / advance.",
    CYCLE_RUNNING: "Идёт Daily Research Cycle.",
    CYCLE_STALE: "Последний успешный цикл устарел относительно EOD.",
    AUTOMATION_DISABLED: "Автоматизация выключена — catch-up не запустится без RESEARCH_LIVE_MODE.",
    BLOCKED_CONSISTENCY: "Консистентность Shadow блокирует готовность.",
    NO_SHADOW_PORTFOLIOS: "Нет активных Shadow-портфелей.",
    PENDING_ORDERS_AWAITING_OPEN: "План готов; ордера ждут OPEN.",
    ORDER_PLAN_PENDING: "EOD готов, но order plan ещё не сформирован.",
}


def _summary(code: str) -> dict[str, str]:
    return {"code": code, "message_ru": _SUMMARY_RU.get(code, code)}


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


@dataclass(frozen=True, slots=True)
class DailyDecisionPipelineStatus:
    watermarks: dict[str, Any]
    current_session_status: str
    next_session_preparation_status: str
    mid_session_activation: bool
    today_summary: dict[str, str]
    next_session_summary: dict[str, str]
    automation_warning: str | None
    as_of_clock: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "watermarks": self.watermarks,
            "current_session_status": self.current_session_status,
            "next_session_preparation_status": self.next_session_preparation_status,
            "mid_session_activation": self.mid_session_activation,
            "today_summary": self.today_summary,
            "next_session_summary": self.next_session_summary,
            "automation_warning": self.automation_warning,
            "as_of_clock": self.as_of_clock,
        }


def _serialize_watermarks(wm: dict[str, Any]) -> dict[str, Any]:
    return {
        "market": _iso(wm.get("raw_market_latest_date")),
        "analytics": _iso(wm.get("analytics_v2_latest_date")),
        "technical": _iso(wm.get("technical_v2_latest_date")),
        "relations": _iso(wm.get("relations_v2_latest_as_of")),
        "forward": _iso(wm.get("forward_latest_as_of")),
        "shadow_plan": _iso(wm.get("shadow_plan_latest_as_of")),
    }


def _shadow_plan_as_of(session: Session) -> date | None:
    decision_as_of = session.scalar(select(func.max(ShadowDecision.signal_as_of_date)))
    processed = session.scalar(select(func.max(ShadowPortfolio.last_processed_market_date)))
    dates = [d for d in (decision_as_of, processed) if d is not None]
    return max(dates) if dates else None


def _active_shadow_specs(session: Session) -> list[tuple[ShadowPortfolio, ShadowPortfolioSpec]]:
    return list(
        session.execute(
            select(ShadowPortfolio, ShadowPortfolioSpec)
            .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
            .where(ShadowPortfolioSpec.experiment_group.in_([EXPERIMENT_GROUP, EXPERIMENT_GROUP_V2]))
            .order_by(ShadowPortfolio.id)
        ).all()
    )


def detect_mid_session_activation(
    session: Session,
    *,
    now: datetime | None = None,
    portfolios: list[tuple[ShadowPortfolio, ShadowPortfolioSpec]] | None = None,
) -> tuple[bool, str]:
    """True when any active Shadow was activated at/after today's session open."""
    clock = ensure_aware_utc(now or datetime.now(UTC))
    today = clock.date()
    open_at = session_open_time_utc(today)
    specs = portfolios if portfolios is not None else _active_shadow_specs(session)
    for portfolio, _spec in specs:
        activated = ensure_aware_utc(portfolio.activated_at)
        if activated >= open_at and activated.date() == today:
            return True, CURRENT_MID_SESSION_WAIT
    # Also: pending orders created after today's open targeting today or tomorrow
    pending = list(
        session.scalars(
            select(ShadowOrder).where(ShadowOrder.status == "PENDING").order_by(ShadowOrder.id)
        ).all()
    )
    for order in pending:
        created = ensure_aware_utc(order.created_at)
        if created >= open_at and created.date() == today:
            return True, CURRENT_FILLS_BLOCKED_AFTER_OPEN
    return False, CURRENT_NO_ACTIVITY


def build_pipeline_status(
    session: Session,
    *,
    readiness: Any,
    wm: dict[str, Any],
    running: bool,
    stale: bool,
    pending_n: int,
    cycle_covers: bool,
    consistency_blocked: bool,
    has_portfolios: bool,
    now: datetime | None = None,
) -> DailyDecisionPipelineStatus:
    """Compose current-session vs next-session-prep statuses for daily-operations."""
    settings = get_settings()
    clock = ensure_aware_utc(now or datetime.now(UTC))
    wm_full = dict(wm)
    wm_full["shadow_plan_latest_as_of"] = _shadow_plan_as_of(session)

    mid, mid_code = detect_mid_session_activation(session, now=clock)
    if mid:
        current = mid_code
    elif pending_n > 0:
        current = CURRENT_PENDING_AWAITING_OPEN
    elif clock >= session_open_time_utc(clock.date()) and clock.hour < 18:
        current = CURRENT_SESSION_ACTIVE
    else:
        current = CURRENT_NO_ACTIVITY

    automation_on = bool(
        settings.research_live_mode
        or settings.daily_research_cycle_enabled
        or settings.eod_readiness_retry_enabled
    )
    lagging = False
    eod = readiness.latest_complete_eod_date
    analytics = wm_full.get("analytics_v2_latest_date")
    technical = wm_full.get("technical_v2_latest_date")
    forward = wm_full.get("forward_latest_as_of")
    if eod is not None:
        if analytics is None or analytics < eod or technical is None or technical < eod:
            lagging = True
        if forward is None or forward < eod:
            lagging = True

    automation_warning = None
    if has_portfolios and lagging and not automation_on:
        automation_warning = AUTOMATION_DISABLED

    if not has_portfolios:
        prep = NO_SHADOW_PORTFOLIOS
    elif consistency_blocked:
        prep = BLOCKED_CONSISTENCY
    elif running:
        prep = CYCLE_RUNNING
    elif stale:
        prep = CYCLE_STALE
    elif not readiness.ready:
        prep = readiness.blocker_code or WAITING_FOR_MARKET_COMPLETE
        if prep == WAITING_FOR_ANALYTICS and not automation_on:
            # Keep analytics code but surface automation warning separately.
            pass
    elif not cycle_covers:
        if forward is None or (eod is not None and forward < eod):
            prep = WAITING_FOR_FORWARD
        else:
            prep = ORDER_PLAN_PENDING
    elif pending_n > 0:
        prep = PENDING_ORDERS_AWAITING_OPEN
    elif cycle_covers and pending_n == 0:
        prep = READY_NO_REBALANCE
    else:
        prep = READY_FOR_NEXT_SESSION

    return DailyDecisionPipelineStatus(
        watermarks=_serialize_watermarks(wm_full),
        current_session_status=current,
        next_session_preparation_status=prep,
        mid_session_activation=mid,
        today_summary=_summary(current),
        next_session_summary=_summary(prep if automation_warning is None else prep),
        automation_warning=(
            _SUMMARY_RU[AUTOMATION_DISABLED] if automation_warning else None
        ),
        as_of_clock=clock.isoformat(),
    )


def next_session_date_from_eod(eod: date | None) -> str | None:
    if eod is None:
        return None
    return (eod + timedelta(days=1)).isoformat()
