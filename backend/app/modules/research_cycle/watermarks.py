"""Watermark and operational health read model."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.analytics.models import FeatureSet, InstrumentFeatureDaily
from app.infrastructure.analytics.relation_models import RelationSet, RelationSnapshot
from app.infrastructure.market.models import Candle, Workflow
from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily
from app.modules.prediction.application.forward_config import (
    FORWARD_BASIC_FS_CODE,
    FORWARD_BASIC_FS_VERSION,
    FORWARD_MAX_RELATION_AGE_DAYS,
    FORWARD_RELATION_SET_CODE,
    FORWARD_RELATION_SET_VERSION,
    FORWARD_TECH_FS_CODE,
    FORWARD_TECH_FS_VERSION,
)
from app.modules.prediction.application.forward_outcome import cohort_future_observation_count
from app.modules.prediction.infrastructure.forward_models import ForwardPredictionBatch
from app.modules.prediction.infrastructure.forward_outcome_models import ForwardBatchEvaluation
from app.modules.research_cycle.config import CYCLE_WORKFLOW_TYPE
from app.modules.shadow.infrastructure.models import ShadowPortfolio
from app.modules.technical.technical_config import RULES_V1_CODE, RULES_V2_VERSION


def _max_candle_date(session: Session) -> date | None:
    ts = session.scalar(select(func.max(Candle.timestamp)).where(Candle.timeframe == "1d"))
    return ts.date() if ts is not None else None


def _analytics_v2_latest(session: Session) -> date | None:
    fs = session.scalar(
        select(FeatureSet).where(
            FeatureSet.code == FORWARD_BASIC_FS_CODE,
            FeatureSet.version == FORWARD_BASIC_FS_VERSION,
        )
    )
    if fs is None:
        return None
    return session.scalar(
        select(func.max(InstrumentFeatureDaily.date)).where(InstrumentFeatureDaily.feature_set_id == fs.id)
    )


def _technical_v2_latest(session: Session) -> date | None:
    fs = session.scalar(
        select(FeatureSet).where(
            FeatureSet.code == FORWARD_TECH_FS_CODE,
            FeatureSet.version == FORWARD_TECH_FS_VERSION,
        )
    )
    if fs is None:
        return None
    return session.scalar(
        select(func.max(InstrumentTechnicalFeatureDaily.date)).where(
            InstrumentTechnicalFeatureDaily.feature_set_id == fs.id
        )
    )


def _relations_v2_latest(session: Session) -> date | None:
    rs = session.scalar(
        select(RelationSet).where(
            RelationSet.code == FORWARD_RELATION_SET_CODE,
            RelationSet.version == FORWARD_RELATION_SET_VERSION,
        )
    )
    if rs is None:
        return None
    return session.scalar(
        select(func.max(RelationSnapshot.as_of_date)).where(RelationSnapshot.relation_set_id == rs.id)
    )


def _forward_latest(session: Session) -> ForwardPredictionBatch | None:
    return session.scalar(
        select(ForwardPredictionBatch).order_by(
            ForwardPredictionBatch.as_of_date.desc(),
            ForwardPredictionBatch.id.desc(),
        )
    )


def collect_watermarks(session: Session) -> dict[str, Any]:
    fwd = _forward_latest(session)
    shadows = list(session.scalars(select(ShadowPortfolio).order_by(ShadowPortfolio.id)).all())
    outcome_as_of = session.scalar(
        select(func.max(ForwardBatchEvaluation.evaluated_at))
    )
    latest_eval = session.scalar(
        select(ForwardBatchEvaluation).order_by(ForwardBatchEvaluation.id.desc())
    )
    return {
        "raw_market_latest_date": _max_candle_date(session),
        "analytics_v2_latest_date": _analytics_v2_latest(session),
        "technical_v2_latest_date": _technical_v2_latest(session),
        "relations_v2_latest_as_of": _relations_v2_latest(session),
        "forward_latest_as_of": fwd.as_of_date if fwd else None,
        "forward_latest_generated_at": fwd.generated_at if fwd else None,
        "forward_latest_batch_id": fwd.id if fwd else None,
        "shadow_portfolios": [
            {
                "id": p.id,
                "status": p.status,
                "last_processed_market_date": p.last_processed_market_date,
                "cash": float(p.cash) if p.cash is not None else None,
                "peak_nav": float(p.peak_nav) if p.peak_nav is not None else None,
            }
            for p in shadows
        ],
        "forward_outcome_latest_status": latest_eval.status if latest_eval else None,
        "forward_outcome_latest_evaluated_at": outcome_as_of,
        "max_relation_age_days": FORWARD_MAX_RELATION_AGE_DAYS,
        "technical_model_pin": {"code": RULES_V1_CODE, "version": RULES_V2_VERSION},
    }


def determine_health(watermarks: dict[str, Any], *, running: bool = False, blocked: bool = False) -> str:
    if running:
        return "RUNNING"
    if blocked:
        return "BLOCKED"
    market = watermarks.get("raw_market_latest_date")
    analytics = watermarks.get("analytics_v2_latest_date")
    technical = watermarks.get("technical_v2_latest_date")
    forward = watermarks.get("forward_latest_as_of")
    if market is None:
        return "WAITING_FOR_MARKET"
    lagging = False
    for d in (analytics, technical, forward):
        if d is not None and market is not None and d < market:
            lagging = True
            break
    if lagging:
        return "LAGGING"
    # Downstream caught up to available market (or forward intentionally same)
    if forward is not None and market is not None and forward == market:
        return "IN_SYNC"
    if analytics == market and technical == market:
        return "WAITING_FOR_MARKET" if forward == market or forward is None else "IN_SYNC"
    if analytics == market and technical == market and (forward is None or forward <= market):
        return "WAITING_FOR_MARKET"
    return "IN_SYNC"


def relations_due(session: Session, signal_as_of: date | None) -> tuple[bool, str]:
    """Return (should_compute, reason)."""
    if signal_as_of is None:
        return False, "no_signal_as_of"
    latest = _relations_v2_latest(session)
    if latest is None:
        return True, "missing_snapshot"
    age = (signal_as_of - latest).days
    if latest <= signal_as_of and age <= FORWARD_MAX_RELATION_AGE_DAYS:
        return False, "SKIPPED_NOT_DUE"
    return True, "stale_or_future_gap"


def serialize_watermarks(wm: dict[str, Any]) -> dict[str, Any]:
    def _d(v: Any) -> str | None:
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)

    return {
        "raw_market_latest_date": _d(wm.get("raw_market_latest_date")),
        "analytics_v2_latest_date": _d(wm.get("analytics_v2_latest_date")),
        "technical_v2_latest_date": _d(wm.get("technical_v2_latest_date")),
        "relations_v2_latest_as_of": _d(wm.get("relations_v2_latest_as_of")),
        "forward_latest_as_of": _d(wm.get("forward_latest_as_of")),
        "forward_latest_generated_at": _d(wm.get("forward_latest_generated_at")),
        "forward_latest_batch_id": wm.get("forward_latest_batch_id"),
        "shadow_portfolios": [
            {
                **p,
                "last_processed_market_date": _d(p.get("last_processed_market_date")),
            }
            for p in (wm.get("shadow_portfolios") or [])
        ],
        "forward_outcome_latest_status": wm.get("forward_outcome_latest_status"),
        "forward_outcome_latest_evaluated_at": _d(wm.get("forward_outcome_latest_evaluated_at")),
        "max_relation_age_days": wm.get("max_relation_age_days"),
        "technical_model_pin": wm.get("technical_model_pin"),
    }


def latest_cycle_workflow(session: Session) -> Workflow | None:
    return session.scalar(
        select(Workflow)
        .where(Workflow.workflow_type == CYCLE_WORKFLOW_TYPE)
        .order_by(Workflow.id.desc())
    )


def build_operational_status(session: Session) -> dict[str, Any]:
    settings = get_settings()
    wm = collect_watermarks(session)
    latest = latest_cycle_workflow(session)
    running = latest is not None and str(latest.status).upper() == "RUNNING"
    health = determine_health(wm, running=running)
    fwd = _forward_latest(session)
    outcome_maturity = None
    if fwd is not None:
        obs = cohort_future_observation_count(session, fwd.as_of_date)
        outcome_maturity = {
            "batch_id": fwd.id,
            "as_of": fwd.as_of_date.isoformat(),
            "future_trading_observations": obs,
            "required": 20,
            "status": "Ожидаем" if obs < 20 else "Готово к оценке",
            "matured": obs >= 20,
        }
    return {
        "health": health,
        "health_human": {
            "IN_SYNC": "Контур синхронизирован",
            "WAITING_FOR_MARKET": "Ожидаем новые рыночные данные",
            "LAGGING": "Есть отставание downstream",
            "BLOCKED": "Контур заблокирован",
            "RUNNING": "Идёт ежедневный цикл",
        }.get(health, health),
        "watermarks": serialize_watermarks(wm),
        "latest_cycle": _workflow_brief(latest),
        "schedule": {
            "enabled": bool(getattr(settings, "daily_research_cycle_enabled", False)),
            "hour": getattr(settings, "daily_research_cycle_hour", 18),
            "minute": getattr(settings, "daily_research_cycle_minute", 30),
            "timezone": getattr(settings, "daily_research_cycle_timezone", "UTC"),
        },
        "outcome_maturity": outcome_maturity,
        "automatic_schedule": "enabled"
        if getattr(settings, "daily_research_cycle_enabled", False)
        else "disabled",
    }


def _workflow_brief(wf: Workflow | None) -> dict[str, Any] | None:
    if wf is None:
        return None
    meta = wf.meta or {}
    return {
        "id": wf.id,
        "name": wf.name,
        "status": wf.status,
        "started_at": wf.started_at.isoformat() if wf.started_at else None,
        "finished_at": wf.finished_at.isoformat() if wf.finished_at else None,
        "error": wf.error,
        "market_watermark_before": meta.get("market_watermark_before"),
        "market_watermark_after": meta.get("market_watermark_after"),
        "latest_forward_batch_id": meta.get("latest_forward_batch_id"),
        "health": meta.get("health"),
        "duration_seconds": meta.get("duration_seconds"),
        "step_results": meta.get("step_results"),
    }
