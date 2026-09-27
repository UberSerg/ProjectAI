"""Deterministic Shadow session catch-up after downtime.

Contract:
  last_processed_session
    → latest_completed_market_session
    → missing_sessions[]  (observed 1d candle dates, ascending)
    → ensure_market_data
    → process_shadow_market_day(session) per day
    → next

Does not create a parallel Shadow engine: reuses production day processing
from ``service.process_shadow_market_day`` / ``advance_shadow_portfolio``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.shadow.application.daily_operations import evaluate_eod_readiness
from app.modules.shadow.application.service import (
    apply_pending_forward_decisions,
    list_trading_sessions_after,
    process_shadow_market_day,
    refresh_shadow_portfolio_status,
    session_has_eod_candles,
)
from app.modules.shadow.config import operational_experiment_groups
from app.modules.shadow.infrastructure.models import (
    ShadowFill,
    ShadowNavDaily,
    ShadowPortfolio,
    ShadowPortfolioSpec,
)

Clock = Callable[[], datetime]

CATCH_UP_NO_OP = "CATCH_UP_NO_OP"
CATCH_UP_SUCCESS = "CATCH_UP_SUCCESS"
CATCH_UP_BLOCKED = "CATCH_UP_BLOCKED"
CATCH_UP_PARTIAL = "CATCH_UP_PARTIAL"

REASON_MISSING_MARKET_DATA = "MISSING_MARKET_DATA"
REASON_NO_COMPLETE_EOD = "NO_COMPLETE_EOD"
REASON_NO_PORTFOLIO = "NO_PORTFOLIO"
REASON_ALREADY_CURRENT = "ALREADY_CURRENT"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class PortfolioCatchUpPlan:
    portfolio_id: int
    name: str
    last_processed_session: date | None
    latest_completed_market_session: date | None
    missing_sessions: list[date] = field(default_factory=list)
    backlog_count: int = 0
    status: str = CATCH_UP_NO_OP
    blocking_session: date | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "name": self.name,
            "last_processed_session": (
                self.last_processed_session.isoformat() if self.last_processed_session else None
            ),
            "latest_completed_market_session": (
                self.latest_completed_market_session.isoformat()
                if self.latest_completed_market_session
                else None
            ),
            "missing_sessions": [d.isoformat() for d in self.missing_sessions],
            "backlog_count": self.backlog_count,
            "status": self.status,
            "blocking_session": (
                self.blocking_session.isoformat() if self.blocking_session else None
            ),
            "reason": self.reason,
        }


def _operational_portfolios(session: Session) -> list[tuple[ShadowPortfolio, ShadowPortfolioSpec]]:
    groups = list(operational_experiment_groups())
    rows = list(
        session.scalars(
            select(ShadowPortfolio)
            .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
            .where(ShadowPortfolioSpec.experiment_group.in_(groups))
            .order_by(ShadowPortfolio.id)
        )
    )
    out: list[tuple[ShadowPortfolio, ShadowPortfolioSpec]] = []
    for p in rows:
        spec = session.get(ShadowPortfolioSpec, p.spec_id)
        if spec is not None:
            out.append((p, spec))
    return out


def missing_sessions_for_watermark(
    session: Session,
    *,
    last_processed: date | None,
    latest_completed: date | None,
) -> list[date]:
    """Trading sessions strictly after watermark, not beyond latest complete EOD."""
    if latest_completed is None:
        return []
    days = list_trading_sessions_after(session, last_processed)
    return [d for d in days if d <= latest_completed]


def build_portfolio_catchup_plan(
    session: Session,
    portfolio: ShadowPortfolio,
    spec: ShadowPortfolioSpec,
    *,
    latest_completed: date | None,
) -> PortfolioCatchUpPlan:
    last = portfolio.last_processed_market_date
    missing = missing_sessions_for_watermark(
        session, last_processed=last, latest_completed=latest_completed
    )
    plan = PortfolioCatchUpPlan(
        portfolio_id=int(portfolio.id),
        name=str(spec.name),
        last_processed_session=last,
        latest_completed_market_session=latest_completed,
        missing_sessions=missing,
        backlog_count=len(missing),
    )
    if latest_completed is None:
        plan.status = CATCH_UP_BLOCKED
        plan.reason = REASON_NO_COMPLETE_EOD
        return plan
    if last is not None and last >= latest_completed:
        plan.status = CATCH_UP_NO_OP
        plan.reason = REASON_ALREADY_CURRENT
        return plan
    if not missing:
        plan.status = CATCH_UP_BLOCKED
        plan.blocking_session = (
            date.fromordinal(last.toordinal() + 1) if last is not None else latest_completed
        )
        plan.reason = REASON_MISSING_MARKET_DATA
        return plan
    plan.status = CATCH_UP_PARTIAL
    return plan


def build_catchup_status(session: Session) -> dict[str, Any]:
    """Observability snapshot for OWNER / daily-operations."""
    readiness = evaluate_eod_readiness(session)
    latest = readiness.latest_complete_eod_date
    portfolios = _operational_portfolios(session)
    plans = [build_portfolio_catchup_plan(session, p, s, latest_completed=latest) for p, s in portfolios]
    backlog = max((pl.backlog_count for pl in plans), default=0)
    blocked = next(
        (pl for pl in plans if pl.status == CATCH_UP_BLOCKED and pl.reason == REASON_MISSING_MARKET_DATA),
        None,
    )
    any_work = any(pl.backlog_count > 0 for pl in plans)
    if blocked is not None and not any_work:
        overall = CATCH_UP_BLOCKED
    elif any_work:
        overall = CATCH_UP_PARTIAL
    else:
        overall = CATCH_UP_NO_OP
    return {
        "catch_up_status": overall,
        "latest_completed_market_session": latest.isoformat() if latest else None,
        "backlog_session_count": backlog,
        "blocking_session": (
            blocked.blocking_session.isoformat() if blocked and blocked.blocking_session else None
        ),
        "blocking_reason": blocked.reason if blocked else None,
        "last_successful_replay_hint": (
            max(
                (pl.last_processed_session for pl in plans if pl.last_processed_session is not None),
                default=None,
            ).isoformat()
            if any(pl.last_processed_session is not None for pl in plans)
            else None
        ),
        "portfolios": [pl.to_dict() for pl in plans],
        "eod_readiness": readiness.to_dict(),
    }


def ensure_market_data_for_catchup(session: Session) -> dict[str, Any]:
    """Lawful incremental market ingest (existing provider). No new data source."""
    from app.modules.market.application.ingest import MarketIngestionService

    return MarketIngestionService(session).run_update()


def shadow_has_catchup_lag(session: Session) -> bool:
    """True when any operational Shadow watermark is behind latest complete EOD."""
    status = build_catchup_status(session)
    if status.get("catch_up_status") == CATCH_UP_BLOCKED:
        return True
    return int(status.get("backlog_session_count") or 0) > 0


def run_portfolio_session_catchup(
    session: Session,
    portfolio_id: int,
    *,
    clock: Clock | None = None,
    ensure_market: bool = True,
    commit_each_session: bool = False,
    max_sessions: int | None = None,
) -> dict[str, Any]:
    """Catch up one portfolio day-by-day using production session processing.

    When ``commit_each_session`` is True, commits after each successful day so a
    crash can resume without replaying completed sessions.
    """
    now_fn = clock or _utcnow
    portfolio = session.get(ShadowPortfolio, portfolio_id)
    if portfolio is None:
        return {
            "status": CATCH_UP_BLOCKED,
            "reason": REASON_NO_PORTFOLIO,
            "portfolio_id": portfolio_id,
            "sessions_replayed": [],
        }
    spec = session.get(ShadowPortfolioSpec, portfolio.spec_id)
    if spec is None:
        return {
            "status": CATCH_UP_BLOCKED,
            "reason": REASON_NO_PORTFOLIO,
            "portfolio_id": portfolio_id,
            "sessions_replayed": [],
        }

    started_at = now_fn()
    market_ensure: dict[str, Any] | None = None
    if ensure_market:
        try:
            market_ensure = ensure_market_data_for_catchup(session)
            if commit_each_session:
                session.commit()
        except Exception as exc:  # noqa: BLE001
            market_ensure = {"error": str(exc)[:500]}

    readiness = evaluate_eod_readiness(session)
    latest = readiness.latest_complete_eod_date
    plan = build_portfolio_catchup_plan(session, portfolio, spec, latest_completed=latest)

    if plan.status == CATCH_UP_NO_OP:
        return {
            "status": CATCH_UP_NO_OP,
            "reason": plan.reason,
            "portfolio_id": portfolio_id,
            "name": spec.name,
            "sessions_replayed": [],
            "last_processed_session": (
                plan.last_processed_session.isoformat() if plan.last_processed_session else None
            ),
            "latest_completed_market_session": (
                plan.latest_completed_market_session.isoformat()
                if plan.latest_completed_market_session
                else None
            ),
            "backlog_remaining": 0,
            "started_at": started_at.isoformat(),
            "market_ensure": market_ensure,
        }

    if plan.status == CATCH_UP_BLOCKED and not plan.missing_sessions:
        return {
            "status": CATCH_UP_BLOCKED,
            "reason": plan.reason,
            "portfolio_id": portfolio_id,
            "name": spec.name,
            "blocking_session": (
                plan.blocking_session.isoformat() if plan.blocking_session else None
            ),
            "sessions_replayed": [],
            "last_processed_session": (
                plan.last_processed_session.isoformat() if plan.last_processed_session else None
            ),
            "latest_completed_market_session": (
                plan.latest_completed_market_session.isoformat()
                if plan.latest_completed_market_session
                else None
            ),
            "backlog_remaining": 0,
            "started_at": started_at.isoformat(),
            "market_ensure": market_ensure,
        }

    now = now_fn()
    decisions_made = apply_pending_forward_decisions(session, portfolio, spec, now=now)
    session.flush()
    if commit_each_session:
        session.commit()
        session.refresh(portfolio)

    plan = build_portfolio_catchup_plan(session, portfolio, spec, latest_completed=latest)
    sessions = list(plan.missing_sessions)
    if max_sessions is not None:
        sessions = sessions[: max(0, int(max_sessions))]

    replayed: list[dict[str, Any]] = []
    blocking_session: date | None = None
    block_reason: str | None = None

    for day in sessions:
        if not session_has_eod_candles(session, day):
            blocking_session = day
            block_reason = REASON_MISSING_MARKET_DATA
            break
        last = portfolio.last_processed_market_date
        if last is not None and day <= last:
            continue
        now = now_fn()
        result = process_shadow_market_day(session, portfolio, spec, day, now=now)
        refresh_shadow_portfolio_status(session, portfolio, now=now)
        session.flush()
        if commit_each_session:
            session.commit()
            session.refresh(portfolio)
        replayed.append(result)

    final_last = portfolio.last_processed_market_date
    remaining = missing_sessions_for_watermark(
        session, last_processed=final_last, latest_completed=latest
    )
    if blocking_session is not None:
        status = CATCH_UP_BLOCKED
    elif remaining:
        status = CATCH_UP_PARTIAL
    elif replayed or (final_last is not None and latest is not None and final_last >= latest):
        status = CATCH_UP_SUCCESS
    else:
        status = CATCH_UP_NO_OP

    return {
        "status": status,
        "reason": block_reason,
        "portfolio_id": portfolio_id,
        "name": spec.name,
        "decisions_made": decisions_made,
        "sessions_replayed": replayed,
        "sessions_replayed_dates": [r["day"] for r in replayed],
        "blocking_session": blocking_session.isoformat() if blocking_session else None,
        "last_processed_session": final_last.isoformat() if final_last else None,
        "latest_completed_market_session": latest.isoformat() if latest else None,
        "backlog_remaining": len(remaining),
        "started_at": started_at.isoformat(),
        "finished_at": now_fn().isoformat(),
        "market_ensure": market_ensure,
    }


def run_all_shadow_catchup(
    session: Session,
    *,
    clock: Clock | None = None,
    ensure_market: bool = True,
    commit_each_session: bool = False,
    experiment_groups: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Catch up all operational Shadow portfolios."""
    started = (clock or _utcnow)()
    market_ensure: dict[str, Any] | None = None
    if ensure_market:
        try:
            market_ensure = ensure_market_data_for_catchup(session)
            if commit_each_session:
                session.commit()
        except Exception as exc:  # noqa: BLE001
            market_ensure = {"error": str(exc)[:500]}

    groups = (
        list(experiment_groups) if experiment_groups is not None else list(operational_experiment_groups())
    )
    rows = list(
        session.scalars(
            select(ShadowPortfolio)
            .join(ShadowPortfolioSpec, ShadowPortfolio.spec_id == ShadowPortfolioSpec.id)
            .where(ShadowPortfolioSpec.experiment_group.in_(groups))
            .order_by(ShadowPortfolio.id)
        )
    )
    results = [
        run_portfolio_session_catchup(
            session,
            p.id,
            clock=clock,
            ensure_market=False,
            commit_each_session=commit_each_session,
        )
        for p in rows
    ]
    statuses = {r.get("status") for r in results}
    if CATCH_UP_BLOCKED in statuses:
        overall = CATCH_UP_BLOCKED
    elif CATCH_UP_PARTIAL in statuses:
        overall = CATCH_UP_PARTIAL
    elif CATCH_UP_SUCCESS in statuses:
        overall = CATCH_UP_SUCCESS
    else:
        overall = CATCH_UP_NO_OP

    return {
        "status": overall,
        "started_at": started.isoformat(),
        "finished_at": (clock or _utcnow)().isoformat(),
        "market_ensure": market_ensure,
        "portfolios": results,
        "observability": build_catchup_status(session),
    }


def count_shadow_fills(session: Session, portfolio_id: int) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(ShadowFill).where(ShadowFill.portfolio_id == portfolio_id)
        )
        or 0
    )


def count_shadow_nav(session: Session, portfolio_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ShadowNavDaily)
            .where(ShadowNavDaily.portfolio_id == portfolio_id)
        )
        or 0
    )


__all__ = [
    "CATCH_UP_BLOCKED",
    "CATCH_UP_NO_OP",
    "CATCH_UP_PARTIAL",
    "CATCH_UP_SUCCESS",
    "REASON_ALREADY_CURRENT",
    "REASON_MISSING_MARKET_DATA",
    "REASON_NO_COMPLETE_EOD",
    "REASON_NO_PORTFOLIO",
    "PortfolioCatchUpPlan",
    "build_catchup_status",
    "build_portfolio_catchup_plan",
    "count_shadow_fills",
    "count_shadow_nav",
    "ensure_market_data_for_catchup",
    "missing_sessions_for_watermark",
    "run_all_shadow_catchup",
    "run_portfolio_session_catchup",
    "shadow_has_catchup_lag",
]
