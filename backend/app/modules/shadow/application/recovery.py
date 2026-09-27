"""End-to-end recovery after downtime:

stale EOD → detect market gap → backfill all missing EOD → verify sessions
→ analytics/technical catch-up → intermediate Forward as_of → Shadow session replay.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.modules.market.application.eod_gap import (
    MARKET_CURRENT,
    MARKET_STALE,
    candle_dates_in_range,
    detect_market_eod_gap,
    trading_sessions_between,
)
from app.modules.market.application.eod_recovery import (
    MARKET_BACKFILL_NOOP,
    run_eod_market_recovery,
)
from app.modules.prediction.application.forward_readiness import select_latest_complete_as_of
from app.modules.prediction.application.forward_runner import run_forward_signal_v0
from app.modules.shadow.application.session_catchup import (
    CATCH_UP_NO_OP,
    CATCH_UP_SUCCESS,
    build_catchup_status,
    run_all_shadow_catchup,
)

Clock = Callable[[], datetime]


def _session_as_of_clock(day: date) -> datetime:
    """Decision/visibility clock for a completed session (UTC evening of the session day)."""
    return datetime.combine(day, time(18, 0), tzinfo=UTC)


def _ensure_features(session: Session) -> dict[str, Any]:
    """Compute Analytics/Technical using the same pins as Daily Research Cycle / Forward."""
    from app.modules.analytics.application.compute import FeatureComputeService
    from app.modules.prediction.application.forward_config import (
        FORWARD_BASIC_FS_CODE,
        FORWARD_BASIC_FS_VERSION,
        FORWARD_TECH_MODEL_CODE,
        FORWARD_TECH_MODEL_VERSION,
    )
    from app.modules.research_cycle.config import (
        ANALYTICS_CODE,
        ANALYTICS_VERSION,
        TECHNICAL_MODEL_CODE,
        TECHNICAL_MODEL_VERSION,
    )
    from app.modules.technical.application.compute import TechnicalComputeService

    # Prefer research-cycle pins; they match Forward v2 pins in current production.
    analytics = FeatureComputeService(session).run_update(
        feature_set_code=ANALYTICS_CODE or FORWARD_BASIC_FS_CODE,
        feature_set_version=ANALYTICS_VERSION or FORWARD_BASIC_FS_VERSION,
    )
    technical = TechnicalComputeService(session).run_update(
        model_code=TECHNICAL_MODEL_CODE or FORWARD_TECH_MODEL_CODE,
        model_version=TECHNICAL_MODEL_VERSION or FORWARD_TECH_MODEL_VERSION,
    )
    return {
        "analytics": analytics,
        "technical": technical,
        "pins": {
            "analytics": {"code": ANALYTICS_CODE, "version": ANALYTICS_VERSION},
            "technical": {"code": TECHNICAL_MODEL_CODE, "version": TECHNICAL_MODEL_VERSION},
            "forward_basic": {"code": FORWARD_BASIC_FS_CODE, "version": FORWARD_BASIC_FS_VERSION},
        },
    }


def _backfill_forward_as_of(
    session: Session,
    sessions: list[date],
) -> list[dict[str, Any]]:
    """Generate immutable Forward batches for each recovery session (PIT as_of)."""
    results: list[dict[str, Any]] = []
    for day in sessions:
        gen_at = _session_as_of_clock(day)
        out = run_forward_signal_v0(session, as_of=day, generated_at=gen_at)
        results.append(
            {
                "as_of": day.isoformat(),
                "status": out.status,
                "batch_id": out.batch_id,
                "generated_at": gen_at.isoformat(),
                "error": (out.summary or {}).get("error"),
            }
        )
    return results


def run_market_shadow_recovery(
    session: Session,
    *,
    clock: Clock | None = None,
    commit_each_session: bool = True,
    skip_forward: bool = False,
) -> dict[str, Any]:
    """Full recovery: market multi-day EOD → features → Forward as_of → Shadow replay."""
    now_fn = clock or (lambda: datetime.now(UTC))
    started = now_fn()
    gap_before = detect_market_eod_gap(session, now=started)

    market = run_eod_market_recovery(session, now=started, commit_progress=commit_each_session)
    if commit_each_session:
        session.commit()

    gap_mid = detect_market_eod_gap(session, now=now_fn())
    complete = select_latest_complete_as_of(session)

    features: dict[str, Any] | None = None
    forward_rows: list[dict[str, Any]] = []
    shadow: dict[str, Any] | None = None

    # Feature/forward/shadow only when market moved or still needs downstream catch-up.
    need_downstream = (
        market.get("status") != MARKET_BACKFILL_NOOP
        or gap_before.status == MARKET_STALE
        or gap_mid.status != MARKET_CURRENT
        or (complete.complete and complete.as_of is not None)
    )

    if need_downstream:
        try:
            features = _ensure_features(session)
            if commit_each_session:
                session.commit()
        except Exception as exc:  # noqa: BLE001
            features = {"error": str(exc)[:500]}

        if not skip_forward:
            # Intermediate as_of: every trading session from previous complete → new complete.
            prev = gap_before.local_complete_eod
            target = complete.as_of or gap_mid.expected_completed_session
            sessions = trading_sessions_between(prev, target) if target else []
            # Prefer observed candle dates when available (weekends already absent).
            if prev is not None and target is not None:
                observed = candle_dates_in_range(
                    session,
                    date_from=date.fromordinal(prev.toordinal() + 1),
                    date_to=target,
                )
                if observed:
                    sessions = observed
            try:
                forward_rows = _backfill_forward_as_of(session, sessions)
                if commit_each_session:
                    session.commit()
            except Exception as exc:  # noqa: BLE001
                forward_rows = [{"error": str(exc)[:500]}]

        shadow = run_all_shadow_catchup(
            session,
            clock=clock,
            ensure_market=False,
            commit_each_session=commit_each_session,
        )
        if commit_each_session:
            session.commit()

    gap_after = detect_market_eod_gap(session, now=now_fn())
    observability = build_catchup_status(session)

    shadow_status = (shadow or {}).get("status")
    if gap_after.status == MARKET_CURRENT and shadow_status in (
        CATCH_UP_SUCCESS,
        CATCH_UP_NO_OP,
        None,
    ):
        overall = "RECOVERY_SUCCESS" if market.get("status") != MARKET_BACKFILL_NOOP or shadow else "RECOVERY_NO_OP"
        if market.get("status") == MARKET_BACKFILL_NOOP and shadow_status == CATCH_UP_NO_OP:
            overall = "RECOVERY_NO_OP"
    elif gap_after.status == MARKET_STALE:
        overall = "RECOVERY_MARKET_PARTIAL"
    else:
        overall = "RECOVERY_PARTIAL"

    return {
        "status": overall,
        "started_at": started.isoformat(),
        "finished_at": now_fn().isoformat(),
        "gap_before": gap_before.to_dict(),
        "gap_after": gap_after.to_dict(),
        "market": market,
        "features": features,
        "forward_as_of": forward_rows,
        "shadow": shadow,
        "observability": observability,
        "pit": {
            "intermediate_forward_as_of": True,
            "shadow_session_clock": "per_session_18:00_UTC",
            "max_as_of_on_decisions": True,
            "note": (
                "Forward batches are generated per recovery session with generated_at pinned "
                "to that session; Shadow applies decisions only for as_of <= session day."
            ),
        },
    }


__all__ = ["run_market_shadow_recovery"]
