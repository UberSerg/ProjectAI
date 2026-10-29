"""End-to-end recovery after downtime:

stale EOD → detect market gap → backfill all missing EOD → verify sessions
→ analytics/technical catch-up → intermediate Forward as_of → Shadow session replay.

Counterfactual Forward batches use a PIT visibility clock for replay feasibility, but are
explicitly marked ``history_kind=COUNTERFACTUAL_REPLAY`` so they are never confused with
recorded LIVE history.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from typing import Any

import redis
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.market.application.eod_gap import (
    MARKET_CURRENT,
    MARKET_STALE,
    candle_dates_in_range,
    detect_market_eod_gap,
    trading_sessions_between,
)
from app.modules.market.application.eod_recovery import (
    MARKET_BACKFILL_LOCK_LOST,
    MARKET_BACKFILL_NOOP,
    run_eod_market_recovery,
)
from app.modules.prediction.application.forward_readiness import select_latest_complete_as_of
from app.modules.prediction.application.forward_runner import run_forward_signal_v0
from app.modules.prediction.infrastructure.forward_models import ForwardPredictionBatch
from app.modules.shadow.application.session_catchup import (
    CATCH_UP_NO_OP,
    CATCH_UP_SUCCESS,
    build_catchup_status,
    run_all_shadow_catchup,
)
from app.modules.technical.application.compute import TechnicalComputeLockLost

Clock = Callable[[], datetime]
logger = get_logger(__name__, component="shadow_recovery")

RECOVERY_LOCK_KEY = "projectai:lock:market_shadow_recovery"
RECOVERY_LOCK_TTL_SECONDS = 600  # short lease; renewed while work continues
RECOVERY_HEARTBEAT_SECONDS = 120
RECOVERY_STATUS_KEY = "projectai:status:market_shadow_recovery"
HISTORY_KIND_COUNTERFACTUAL = "COUNTERFACTUAL_REPLAY"
HISTORY_KIND_RECORDED_LIVE = "RECORDED_LIVE"

_RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
else
  return 0
end
"""

_RENEW_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
else
  return 0
end
"""


def _session_as_of_clock(day: date) -> datetime:
    """PIT visibility clock for a completed session (UTC evening of the session day).

    Used so Shadow catch-up can see the batch at historical session time. Batches created
    this way MUST be tagged COUNTERFACTUAL_REPLAY — the clock is not a claim that the
    decision existed live at that wall-clock moment.
    """
    return datetime.combine(day, time(18, 0), tzinfo=UTC)


def _redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=False)


def try_acquire_recovery_lock(token: str, *, ttl: int = RECOVERY_LOCK_TTL_SECONDS) -> bool:
    try:
        return bool(_redis().set(RECOVERY_LOCK_KEY, token, nx=True, ex=ttl))
    except Exception as exc:  # noqa: BLE001
        logger.warning("shadow_recovery_lock_unavailable", extra={"error": str(exc)})
        return False


def renew_recovery_lock(token: str, *, ttl: int = RECOVERY_LOCK_TTL_SECONDS) -> bool:
    """Extend lease only if ``token`` still owns the lock. False ⇒ stop further writes."""
    try:
        client = _redis()
        ok = bool(client.eval(_RENEW_LOCK_LUA, 1, RECOVERY_LOCK_KEY, token, int(ttl)))
        if not ok:
            logger.warning("shadow_recovery_lock_lost", extra={"token": token[:8]})
        return ok
    except Exception as exc:  # noqa: BLE001
        logger.warning("shadow_recovery_lock_renew_failed", extra={"error": str(exc)})
        return False


def release_recovery_lock(token: str) -> bool:
    """Atomic compare-and-delete — only the owner can release."""
    try:
        return bool(_redis().eval(_RELEASE_LOCK_LUA, 1, RECOVERY_LOCK_KEY, token))
    except Exception as exc:  # noqa: BLE001
        logger.warning("shadow_recovery_lock_release_failed", extra={"error": str(exc)})
        return False


def publish_recovery_status(payload: dict[str, Any], *, ttl: int = RECOVERY_LOCK_TTL_SECONDS * 3) -> None:
    """Best-effort status for UI (running / blocked / done)."""
    import json

    try:
        _redis().set(RECOVERY_STATUS_KEY, json.dumps(payload, default=str), ex=max(ttl, 60))
    except Exception as exc:  # noqa: BLE001
        logger.warning("shadow_recovery_status_publish_failed", extra={"error": str(exc)})


def read_recovery_status() -> dict[str, Any] | None:
    import json

    try:
        raw = _redis().get(RECOVERY_STATUS_KEY)
        if raw is None:
            return None
        data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def recovery_lock_held() -> bool:
    try:
        return bool(_redis().exists(RECOVERY_LOCK_KEY))
    except Exception:  # noqa: BLE001
        return False


class RecoveryLockLease:
    """Owner-token lease with background heartbeat during long recovery stages.

    Stage-boundary renew alone is insufficient: market backfill / Forward / Shadow
    loops can exceed ``RECOVERY_LOCK_TTL_SECONDS``. The heartbeat thread extends the
    Redis TTL while work continues; ``still_owned()`` also renews before commits so
    a lost lease stops further financial writes.
    """

    def __init__(
        self,
        token: str,
        *,
        ttl: int = RECOVERY_LOCK_TTL_SECONDS,
        heartbeat_seconds: float = RECOVERY_HEARTBEAT_SECONDS,
        renew_fn: Callable[[str], bool] | None = None,
    ) -> None:
        self.token = token
        self.ttl = int(ttl)
        self.heartbeat_seconds = float(heartbeat_seconds)
        self._renew_fn = renew_fn or (lambda t: renew_recovery_lock(t, ttl=self.ttl))
        self._stop = threading.Event()
        self._owned = True
        self._guard = threading.Lock()
        self._thread: threading.Thread | None = None
        self.renew_count = 0
        self.lost_at: datetime | None = None

    @property
    def owned(self) -> bool:
        with self._guard:
            return self._owned

    def start(self) -> RecoveryLockLease:
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"recovery-lock-{self.token[:8]}",
            daemon=True,
        )
        self._thread.start()
        return self

    def _mark_lost(self) -> None:
        with self._guard:
            if self._owned:
                self._owned = False
                self.lost_at = datetime.now(UTC)
        logger.warning(
            "shadow_recovery_lease_lost",
            extra={"token": self.token[:8], "renew_count": self.renew_count},
        )

    def _heartbeat_loop(self) -> None:
        # First wait then renew — acquisition already set TTL; keep extending mid-stage.
        while not self._stop.wait(self.heartbeat_seconds):
            if not self._renew_fn(self.token):
                self._mark_lost()
                return
            with self._guard:
                self.renew_count += 1

    def still_owned(self) -> bool:
        """Fence before a transactional write: renew now; False ⇒ abort further writes."""
        with self._guard:
            if not self._owned:
                return False
        if not self._renew_fn(self.token):
            self._mark_lost()
            return False
        with self._guard:
            self.renew_count += 1
            return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(2.0, self.heartbeat_seconds + 1.0))
        self._thread = None


def _ensure_features(
    session: Session,
    *,
    renew_lock: Callable[[], bool] | None = None,
) -> dict[str, Any]:
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
    # Technical compute commits internally — fence each durable write with renew_lock.
    technical = TechnicalComputeService(session, commit_guard=renew_lock).run_update(
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


def _batch_history_kind(batch: ForwardPredictionBatch | None) -> str:
    if batch is None:
        return HISTORY_KIND_RECORDED_LIVE
    lineage = batch.input_lineage or {}
    kind = str(lineage.get("history_kind") or "").upper()
    if kind == HISTORY_KIND_COUNTERFACTUAL or lineage.get("reconstruction") is True:
        return HISTORY_KIND_COUNTERFACTUAL
    return HISTORY_KIND_RECORDED_LIVE


def _stamp_new_batch_counterfactual(
    session: Session,
    batch_id: int,
    *,
    as_of: date,
) -> None:
    """Stamp a batch that was just created by this recovery SUCCESS path."""
    batch = session.get(ForwardPredictionBatch, batch_id)
    if batch is None:
        return
    if _batch_history_kind(batch) == HISTORY_KIND_COUNTERFACTUAL:
        return  # idempotent re-stamp: keep original reconstructed_at
    lineage = dict(batch.input_lineage or {})
    lineage["history_kind"] = HISTORY_KIND_COUNTERFACTUAL
    lineage["reconstruction"] = True
    lineage["reconstructed_at"] = datetime.now(UTC).isoformat()
    lineage["pit_visibility_clock"] = _session_as_of_clock(as_of).isoformat()
    lineage["note"] = (
        "Counterfactual recovery replay: PIT inputs as_of session day; "
        "generated_at is a visibility clock for Shadow catch-up, not recorded LIVE history."
    )
    batch.input_lineage = lineage
    session.flush()


def _backfill_forward_as_of(
    session: Session,
    sessions: list[date],
    *,
    renew_lock: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Generate immutable Forward batches for each recovery session (PIT as_of).

    Only newly created SUCCESS batches are tagged COUNTERFACTUAL_REPLAY.
    NO_CHANGES pointing at an existing LIVE (or prior counterfactual) batch is never mutated.
    """
    results: list[dict[str, Any]] = []
    for day in sessions:
        if renew_lock is not None and not renew_lock():
            results.append(
                {
                    "as_of": day.isoformat(),
                    "status": "RECOVERY_LOCK_LOST",
                    "batch_id": None,
                    "generated_at": None,
                    "history_kind": HISTORY_KIND_RECORDED_LIVE,
                    "reconstruction": False,
                    "lineage_mutated": False,
                    "error": "lock_lost_before_forward_session",
                }
            )
            break
        gen_at = _session_as_of_clock(day)
        out = run_forward_signal_v0(session, as_of=day, generated_at=gen_at)
        history_kind = HISTORY_KIND_RECORDED_LIVE
        reconstruction = False
        lineage_mutated = False
        if out.status == "SUCCESS" and out.batch_id is not None:
            before = session.get(ForwardPredictionBatch, out.batch_id)
            before_kind = _batch_history_kind(before)
            _stamp_new_batch_counterfactual(session, out.batch_id, as_of=day)
            history_kind = HISTORY_KIND_COUNTERFACTUAL
            reconstruction = True
            lineage_mutated = before_kind != HISTORY_KIND_COUNTERFACTUAL
        elif out.batch_id is not None:
            # NO_CHANGES / WARNING / ERROR with an existing batch — never rewrite lineage.
            batch = session.get(ForwardPredictionBatch, out.batch_id)
            history_kind = _batch_history_kind(batch)
            reconstruction = history_kind == HISTORY_KIND_COUNTERFACTUAL
        results.append(
            {
                "as_of": day.isoformat(),
                "status": out.status,
                "batch_id": out.batch_id,
                "generated_at": gen_at.isoformat() if out.status == "SUCCESS" else None,
                "history_kind": history_kind,
                "reconstruction": reconstruction,
                "lineage_mutated": lineage_mutated,
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
    lock_token: str | None = None,
    renew_lock: Callable[[], bool] | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Full recovery: market multi-day EOD → features → Forward as_of → Shadow replay.

    When ``renew_lock`` is provided, it is called before each transactional stage.
    Returning False aborts further writes (lock lost / stolen).
    """
    now_fn = clock or (lambda: datetime.now(UTC))
    started = now_fn()

    def _still_owner() -> bool:
        if renew_lock is None:
            return True
        return bool(renew_lock())

    def _status(**extra: Any) -> None:
        publish_recovery_status(
            {
                "state": extra.pop("state", "RUNNING"),
                "task_id": task_id,
                "lock_token_prefix": (lock_token or "")[:8] or None,
                "started_at": started.isoformat(),
                "updated_at": now_fn().isoformat(),
                **extra,
            }
        )

    _status(state="RUNNING", phase="market")
    if not _still_owner():
        return {
            "status": "RECOVERY_LOCK_LOST",
            "started_at": started.isoformat(),
            "finished_at": now_fn().isoformat(),
            "reason": "lock_lost_before_market",
        }

    gap_before = detect_market_eod_gap(session, now=started)

    market = run_eod_market_recovery(
        session,
        now=started,
        commit_progress=commit_each_session,
        commit_guard=_still_owner,
    )
    if market.get("status") == MARKET_BACKFILL_LOCK_LOST or market.get("lock_lost"):
        return {
            "status": "RECOVERY_LOCK_LOST",
            "started_at": started.isoformat(),
            "finished_at": now_fn().isoformat(),
            "market": market,
            "reason": "lock_lost_during_market",
        }
    if commit_each_session:
        if not _still_owner():
            session.rollback()
            return {
                "status": "RECOVERY_LOCK_LOST",
                "started_at": started.isoformat(),
                "finished_at": now_fn().isoformat(),
                "market": market,
                "reason": "lock_lost_after_market",
            }
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
        _status(phase="features")
        if not _still_owner():
            return {
                "status": "RECOVERY_LOCK_LOST",
                "started_at": started.isoformat(),
                "finished_at": now_fn().isoformat(),
                "market": market,
                "reason": "lock_lost_before_features",
            }
        try:
            features = _ensure_features(session, renew_lock=_still_owner)
            if commit_each_session:
                if not _still_owner():
                    session.rollback()
                    return {
                        "status": "RECOVERY_LOCK_LOST",
                        "started_at": started.isoformat(),
                        "finished_at": now_fn().isoformat(),
                        "market": market,
                        "features": features,
                        "reason": "lock_lost_before_features_commit",
                    }
                session.commit()
        except TechnicalComputeLockLost:
            session.rollback()
            return {
                "status": "RECOVERY_LOCK_LOST",
                "started_at": started.isoformat(),
                "finished_at": now_fn().isoformat(),
                "market": market,
                "features": {"error": "recovery_lock_lost"},
                "reason": "lock_lost_during_features",
            }
        except Exception as exc:  # noqa: BLE001
            features = {"error": str(exc)[:500]}

        if not skip_forward:
            _status(phase="forward")
            if not _still_owner():
                return {
                    "status": "RECOVERY_LOCK_LOST",
                    "started_at": started.isoformat(),
                    "finished_at": now_fn().isoformat(),
                    "market": market,
                    "features": features,
                    "reason": "lock_lost_before_forward",
                }
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
                forward_rows = _backfill_forward_as_of(
                    session, sessions, renew_lock=_still_owner
                )
                if any(r.get("status") == "RECOVERY_LOCK_LOST" for r in forward_rows):
                    return {
                        "status": "RECOVERY_LOCK_LOST",
                        "started_at": started.isoformat(),
                        "finished_at": now_fn().isoformat(),
                        "market": market,
                        "features": features,
                        "forward_as_of": forward_rows,
                        "reason": "lock_lost_during_forward",
                    }
                if commit_each_session:
                    if not _still_owner():
                        return {
                            "status": "RECOVERY_LOCK_LOST",
                            "started_at": started.isoformat(),
                            "finished_at": now_fn().isoformat(),
                            "market": market,
                            "features": features,
                            "forward_as_of": forward_rows,
                            "reason": "lock_lost_before_forward_commit",
                        }
                    session.commit()
            except Exception as exc:  # noqa: BLE001
                forward_rows = [{"error": str(exc)[:500]}]

        _status(phase="shadow")
        if not _still_owner():
            return {
                "status": "RECOVERY_LOCK_LOST",
                "started_at": started.isoformat(),
                "finished_at": now_fn().isoformat(),
                "market": market,
                "features": features,
                "forward_as_of": forward_rows,
                "reason": "lock_lost_before_shadow",
            }
        shadow = run_all_shadow_catchup(
            session,
            clock=clock,
            ensure_market=False,
            commit_each_session=commit_each_session,
            renew_lock=_still_owner,
        )
        if (shadow or {}).get("status") == "RECOVERY_LOCK_LOST":
            return {
                "status": "RECOVERY_LOCK_LOST",
                "started_at": started.isoformat(),
                "finished_at": now_fn().isoformat(),
                "market": market,
                "features": features,
                "forward_as_of": forward_rows,
                "shadow": shadow,
                "reason": "lock_lost_during_shadow",
            }
        if commit_each_session:
            if not _still_owner():
                return {
                    "status": "RECOVERY_LOCK_LOST",
                    "started_at": started.isoformat(),
                    "finished_at": now_fn().isoformat(),
                    "market": market,
                    "features": features,
                    "forward_as_of": forward_rows,
                    "shadow": shadow,
                    "reason": "lock_lost_after_shadow",
                }
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

    finished = now_fn()
    _status(
        state="DONE" if overall.startswith("RECOVERY_SUCCESS") or overall == "RECOVERY_NO_OP" else "PARTIAL",
        phase="finished",
        overall=overall,
        last_processed_session=(observability or {}).get("last_successful_replay_hint"),
        remaining_sessions=(observability or {}).get("backlog_session_count"),
        blocking_session=(observability or {}).get("blocking_session"),
        finished_at=finished.isoformat(),
    )

    return {
        "status": overall,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
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
            "history_kind": HISTORY_KIND_COUNTERFACTUAL,
            "recorded_live_kind": HISTORY_KIND_RECORDED_LIVE,
            "note": (
                "Recovery Forward batches are COUNTERFACTUAL_REPLAY: PIT as_of per session, "
                "generated_at is a visibility clock for catch-up only — not recorded LIVE history. "
                "Do not merge reconstructed and recorded performance unsigned."
            ),
        },
    }


__all__ = [
    "HISTORY_KIND_COUNTERFACTUAL",
    "HISTORY_KIND_RECORDED_LIVE",
    "RECOVERY_HEARTBEAT_SECONDS",
    "RECOVERY_LOCK_TTL_SECONDS",
    "RecoveryLockLease",
    "publish_recovery_status",
    "read_recovery_status",
    "recovery_lock_held",
    "release_recovery_lock",
    "renew_recovery_lock",
    "run_market_shadow_recovery",
    "try_acquire_recovery_lock",
]
