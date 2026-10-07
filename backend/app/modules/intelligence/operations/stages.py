"""Stage runners for IntelligenceRefreshV1.

Sibling intelligence modules are optional during parallel agent work.
Missing modules → SKIPPED (MODULE_NOT_AVAILABLE), never fabricated success.
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.modules.intelligence.operations.config import (
    MAX_STAGE_RETRIES,
    REFRESH_STAGES,
    RETRY_BACKOFF_SECONDS,
    RETRYABLE_STAGE_STATUSES,
)

logger = get_logger(__name__, component="intelligence-refresh")

StageFn = Callable[[Session, dict[str, Any]], "StageResult"]


@dataclass
class StageResult:
    status: str
    reason: str | None = None
    changed: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    attempts: int = 1
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "changed": self.changed,
            "details": self.details,
            "attempts": self.attempts,
            "error": self.error,
        }


def _skipped(reason: str, **details: Any) -> StageResult:
    return StageResult(status="SKIPPED", reason=reason, changed=False, details=dict(details))


def _try_call(module_path: str, attr: str, session: Session, ctx: dict[str, Any]) -> StageResult:
    try:
        mod = importlib.import_module(module_path)
    except ImportError:
        return _skipped("MODULE_NOT_AVAILABLE", module=module_path)
    fn = getattr(mod, attr, None)
    if fn is None:
        return _skipped("HOOK_NOT_AVAILABLE", module=module_path, attr=attr)
    raw = fn(session, ctx)
    if isinstance(raw, StageResult):
        return raw
    if isinstance(raw, dict):
        return StageResult(
            status=str(raw.get("status") or "SUCCESS").upper(),
            reason=raw.get("reason"),
            changed=bool(raw.get("changed")),
            details={k: v for k, v in raw.items() if k not in {"status", "reason", "changed"}},
            error=raw.get("error"),
        )
    return StageResult(status="SUCCESS", changed=True, details={"result": str(raw)[:500]})


def stage_market_intraday(session: Session, ctx: dict[str, Any]) -> StageResult:
    return _try_call(
        "app.modules.intelligence.intraday.refresh",
        "refresh_market_intraday",
        session,
        ctx,
    )


def stage_fundamentals(session: Session, ctx: dict[str, Any]) -> StageResult:
    return _try_call(
        "app.modules.intelligence.fundamentals.refresh",
        "refresh_fundamentals",
        session,
        ctx,
    )


def stage_news(session: Session, ctx: dict[str, Any]) -> StageResult:
    return _try_call(
        "app.modules.intelligence.news.refresh",
        "refresh_news",
        session,
        ctx,
    )


def stage_extract_events(session: Session, ctx: dict[str, Any]) -> StageResult:
    return _try_call(
        "app.modules.intelligence.extraction.refresh",
        "refresh_extract_events",
        session,
        ctx,
    )


def stage_macro(session: Session, ctx: dict[str, Any]) -> StageResult:
    return _try_call(
        "app.modules.intelligence.macro.refresh",
        "refresh_macro",
        session,
        ctx,
    )


def stage_build_snapshots(session: Session, ctx: dict[str, Any]) -> StageResult:
    return _try_call(
        "app.modules.intelligence.signals.refresh",
        "refresh_build_snapshots",
        session,
        ctx,
    )


def stage_run_models(session: Session, ctx: dict[str, Any]) -> StageResult:
    return _try_call(
        "app.modules.intelligence.signals.refresh",
        "refresh_run_models",
        session,
        ctx,
    )


def stage_risk(session: Session, ctx: dict[str, Any]) -> StageResult:
    return _try_call(
        "app.modules.intelligence.risk.refresh",
        "refresh_risk",
        session,
        ctx,
    )


def stage_committee(session: Session, ctx: dict[str, Any]) -> StageResult:
    return _try_call(
        "app.modules.intelligence.committee.refresh",
        "refresh_committee",
        session,
        ctx,
    )


def stage_finalize(session: Session, ctx: dict[str, Any]) -> StageResult:
    """Aggregate prior stage outcomes; isolation pin check; no broker/candidate mutations."""
    from app.modules.intelligence.isolation import production_isolation_report

    prior = dict(ctx.get("stage_results") or {})
    changed = any(bool((v or {}).get("changed")) for v in prior.values())
    skipped = [
        name
        for name, payload in prior.items()
        if str((payload or {}).get("status") or "").upper() == "SKIPPED"
    ]
    failed = [
        name
        for name, payload in prior.items()
        if str((payload or {}).get("status") or "").upper() in {"FAILED", "ERROR"}
    ]
    isolation = production_isolation_report()
    status = "SUCCESS"
    if failed:
        status = "WARNING"
    elif not changed and skipped == [n for n in REFRESH_STAGES if n != "FINALIZE"]:
        status = "NO_CHANGES"
    elif not changed:
        status = "NO_CHANGES"
    return StageResult(
        status=status,
        reason="FINALIZE",
        changed=changed,
        details={
            "skipped_stages": skipped,
            "failed_stages": failed,
            "production_isolation": isolation,
            "candidate_promotion": False,
            "shadow_policy_switch": False,
            "real_money_off": True,
        },
    )


DEFAULT_STAGE_RUNNERS: dict[str, StageFn] = {
    "MARKET_INTRADAY": stage_market_intraday,
    "FUNDAMENTALS": stage_fundamentals,
    "NEWS": stage_news,
    "EXTRACT_EVENTS": stage_extract_events,
    "MACRO": stage_macro,
    "BUILD_SNAPSHOTS": stage_build_snapshots,
    "RUN_MODELS": stage_run_models,
    "RISK": stage_risk,
    "COMMITTEE": stage_committee,
    "FINALIZE": stage_finalize,
}


def run_stage_with_retries(
    session: Session,
    name: str,
    runner: StageFn,
    ctx: dict[str, Any],
    *,
    max_retries: int = MAX_STAGE_RETRIES,
    backoff_seconds: float = RETRY_BACKOFF_SECONDS,
) -> StageResult:
    """Execute a stage with bounded retries on FAILED/ERROR only."""
    attempts = 0
    last: StageResult | None = None
    while attempts <= max_retries:
        attempts += 1
        try:
            last = runner(session, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "intelligence_refresh_stage_exception",
                extra={"stage": name, "attempt": attempts, "error": str(exc)[:500]},
            )
            last = StageResult(
                status="FAILED",
                reason="EXCEPTION",
                error=str(exc)[:2000],
                attempts=attempts,
            )
        assert last is not None
        last.attempts = attempts
        if last.status.upper() not in RETRYABLE_STAGE_STATUSES:
            return last
        if attempts <= max_retries:
            time.sleep(backoff_seconds)
    assert last is not None
    return last
