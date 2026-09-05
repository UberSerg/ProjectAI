"""Daily Research Cycle V0 orchestrator.

Reuses existing Market / Analytics / Technical / Relations / Forward / Shadow services.
Does not retrain, does not backfill Forward/Shadow history, does not fabricate outcomes.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import get_logger
from app.infrastructure.db.session import core_session
from app.infrastructure.market.models import Candle, Workflow
from app.modules.analytics.application.compute import FeatureComputeService
from app.modules.market.application.corporate_actions import SplitIngestionService
from app.modules.market.application.ingest import MarketIngestionService
from app.modules.market.application.workflows import (
    create_workflow,
    finish_workflow,
    get_step,
    update_step,
)
from app.modules.prediction.application.forward_outcome import evaluate_forward_outcomes
from app.modules.prediction.application.forward_runner import run_forward_signal_v0
from app.modules.relations.application.compute import RelationsComputeService
from app.modules.research_cycle.config import (
    ANALYTICS_CODE,
    ANALYTICS_VERSION,
    CYCLE_NAME,
    CYCLE_STEPS,
    CYCLE_WORKFLOW_TYPE,
    RELATIONS_CODE,
    RELATIONS_VERSION,
    TECHNICAL_MODEL_CODE,
    TECHNICAL_MODEL_VERSION,
)
from app.modules.research_cycle.locking import try_acquire_cycle_lock
from app.modules.research_cycle.watermarks import (
    build_operational_status,
    collect_watermarks,
    determine_health,
    relations_due,
    serialize_watermarks,
)
from app.modules.shadow.application.service import advance_all_shadow_portfolios
from app.modules.shadow.infrastructure.models import ShadowFill, ShadowOrder, ShadowPortfolio
from app.modules.technical.application.compute import TechnicalComputeService

logger = get_logger(__name__, component="research-cycle")


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _mark(session: Session, workflow: Workflow, name: str, status: str, *, error: str | None = None) -> None:
    update_step(session, get_step(workflow, name), status, error=error)


def _store_step(workflow: Workflow, name: str, payload: dict[str, Any]) -> None:
    meta = dict(workflow.meta or {})
    steps = dict(meta.get("step_results") or {})
    steps[name] = payload
    meta["step_results"] = steps
    workflow.meta = meta
    flag_modified(workflow, "meta")


def _meaningful_change(step_results: dict[str, Any]) -> bool:
    """Business-level change only — ignore Analytics/Technical safety-window rewrites."""
    market = (step_results.get("MARKET_UPDATE") or {}).get("stats") or {}
    if int(market.get("inserted") or 0) + int(market.get("updated") or 0) > 0:
        return True
    ca = step_results.get("CORPORATE_ACTION_UPDATE") or {}
    if int(ca.get("inserted") or 0) + int(ca.get("updated") or 0) > 0:
        return True
    fwd = step_results.get("FORWARD_SIGNAL") or {}
    if fwd.get("created"):
        return True
    shadow = step_results.get("SHADOW_ADVANCE") or {}
    if int(shadow.get("fills_new") or 0) + int(shadow.get("orders_new") or 0) > 0:
        return True
    # New weekly decisions without fills still count
    for r in shadow.get("results") or []:
        if int(r.get("decisions_created") or r.get("orders_created") or 0) > 0:
            return True
    outcome = step_results.get("FORWARD_OUTCOME_EVALUATION") or {}
    if int(outcome.get("evaluated_new") or 0) > 0:
        return True
    rel = step_results.get("RELATIONS_V2") or {}
    if int(rel.get("rows") or 0) > 0 and str(rel.get("status") or "").upper() not in {
        "SKIPPED_NOT_DUE",
        "NO_CHANGES",
    }:
        return True
    return False


def run_daily_research_cycle(
    session: Session | None = None,
    *,
    workflow_id: int | None = None,
) -> dict[str, Any]:
    """Execute one Daily Research Cycle. Caller may pass an open session or None."""
    owns_session = session is None
    if owns_session:
        with core_session() as owned:
            return _run(owned, workflow_id=workflow_id)
    assert session is not None
    return _run(session, workflow_id=workflow_id)


def _run(session: Session, *, workflow_id: int | None) -> dict[str, Any]:
    token = str(uuid.uuid4())
    lock = try_acquire_cycle_lock(token)
    if not lock.acquired:
        # Also treat DB RUNNING cycle as blocked
        return {
            "status": "BLOCKED",
            "reason": "ALREADY_RUNNING",
            "message": "Daily Research Cycle already running",
        }

    started = time.perf_counter()
    workflow: Workflow | None = None
    try:
        if workflow_id is not None:
            workflow = session.get(Workflow, workflow_id)
            if workflow is None:
                raise ValueError(f"workflow not found: {workflow_id}")
        else:
            running = session.scalar(
                select(Workflow).where(
                    Workflow.workflow_type == CYCLE_WORKFLOW_TYPE,
                    Workflow.status == "RUNNING",
                )
            )
            if running is not None:
                return {
                    "status": "BLOCKED",
                    "reason": "ALREADY_RUNNING",
                    "workflow_id": running.id,
                }
            workflow = create_workflow(session, CYCLE_WORKFLOW_TYPE, CYCLE_NAME, CYCLE_STEPS)
            session.commit()

        assert workflow is not None
        before = collect_watermarks(session)
        meta = dict(workflow.meta or {})
        meta["market_watermark_before"] = _iso(before.get("raw_market_latest_date"))
        meta["watermarks_before"] = serialize_watermarks(before)
        workflow.meta = meta
        flag_modified(workflow, "meta")
        session.commit()

        # --- SOURCE_DISCOVERY ---
        _mark(session, workflow, "SOURCE_DISCOVERY", "RUNNING")
        discovery = {
            "status": "SUCCESS",
            "raw_market_latest_date": _iso(before.get("raw_market_latest_date")),
            "forward_latest_as_of": _iso(before.get("forward_latest_as_of")),
            "note": "Discover latest safely available completed market data; do not assume today is complete.",
        }
        _store_step(workflow, "SOURCE_DISCOVERY", discovery)
        _mark(session, workflow, "SOURCE_DISCOVERY", "SUCCESS")
        session.commit()

        # --- MARKET + CBR (single incremental ingest; report both steps) ---
        _mark(session, workflow, "MARKET_UPDATE", "RUNNING")
        _mark(session, workflow, "CBR_UPDATE", "RUNNING")
        market_result = MarketIngestionService(session, commit_progress=False).run_update()
        stats = market_result.get("stats") or {}
        max_ts = session.scalar(select(func.max(Candle.timestamp)))
        market_payload = {
            "status": market_result.get("status", "SUCCESS"),
            "stats": {
                "received": stats.get("received", 0),
                "inserted": stats.get("inserted", 0),
                "updated": stats.get("updated", 0),
                "rejected": stats.get("rejected", 0),
            },
            "child_workflow_id": market_result.get("workflow_id"),
            "watermark_after": _iso(max_ts.date() if max_ts is not None else None),
        }
        cbr_payload = {
            "status": market_result.get("status", "SUCCESS"),
            "note": "CBR series updated inside incremental market update",
            "stats": {"warnings": stats.get("warnings", 0)},
        }
        _store_step(workflow, "MARKET_UPDATE", market_payload)
        _store_step(workflow, "CBR_UPDATE", cbr_payload)
        _mark(session, workflow, "MARKET_UPDATE", "SUCCESS" if market_payload["status"] != "ERROR" else "ERROR")
        _mark(session, workflow, "CBR_UPDATE", "SUCCESS")
        session.commit()

        # --- CORPORATE ACTIONS ---
        _mark(session, workflow, "CORPORATE_ACTION_UPDATE", "RUNNING")
        ca = SplitIngestionService(session).run()
        ca_status = str(ca.get("status") or "SUCCESS").upper()
        ca_payload = {
            "status": ca_status if ca_status != "NO_CHANGES" else "NO_CHANGES",
            "inserted": ca.get("inserted") or ca.get("stats", {}).get("inserted") or 0,
            "updated": ca.get("updated") or ca.get("stats", {}).get("updated") or 0,
            "child_workflow_id": ca.get("workflow_id"),
            "summary": {k: ca.get(k) for k in ("fetched", "resolved", "rejected", "annotated") if k in ca},
        }
        # Normalize empty CA to NO_CHANGES-ish success
        if int(ca_payload["inserted"] or 0) == 0 and int(ca_payload["updated"] or 0) == 0:
            ca_payload["status"] = "NO_CHANGES"
        _store_step(workflow, "CORPORATE_ACTION_UPDATE", ca_payload)
        _mark(session, workflow, "CORPORATE_ACTION_UPDATE", "SUCCESS")
        session.commit()

        # --- ANALYTICS V2 ---
        _mark(session, workflow, "ANALYTICS_V2", "RUNNING")
        t0 = time.perf_counter()
        analytics = FeatureComputeService(session).run_update(
            feature_set_code=ANALYTICS_CODE,
            feature_set_version=ANALYTICS_VERSION,
        )
        rows_a = int(analytics.get("instrument_rows") or 0) + int(analytics.get("series_rows") or 0)
        analytics_payload = {
            "status": "NO_CHANGES" if rows_a == 0 else analytics.get("status", "SUCCESS"),
            "rows": rows_a,
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "pin": {"code": ANALYTICS_CODE, "version": ANALYTICS_VERSION},
            "child_workflow_id": analytics.get("workflow_id"),
        }
        _store_step(workflow, "ANALYTICS_V2", analytics_payload)
        _mark(session, workflow, "ANALYTICS_V2", "SUCCESS")
        session.commit()

        # --- TECHNICAL V2 ---
        _mark(session, workflow, "TECHNICAL_V2", "RUNNING")
        t0 = time.perf_counter()
        try:
            technical = TechnicalComputeService(session).run_update(
                model_code=TECHNICAL_MODEL_CODE,
                model_version=TECHNICAL_MODEL_VERSION,
            )
        except Exception as tech_exc:  # noqa: BLE001
            # Persist FAILED checkpoint without undoing already-committed upstream steps.
            technical_payload = {
                "status": "ERROR",
                "error": str(tech_exc)[:2000],
                "duration_seconds": round(time.perf_counter() - t0, 3),
                "pin": {"code": TECHNICAL_MODEL_CODE, "version": TECHNICAL_MODEL_VERSION},
            }
            _store_step(workflow, "TECHNICAL_V2", technical_payload)
            _mark(session, workflow, "TECHNICAL_V2", "ERROR", error=str(tech_exc)[:2000])
            session.commit()
            finish_workflow(session, workflow, "FAILED", error=f"TECHNICAL_V2: {tech_exc}"[:2000])
            session.commit()
            return {
                "status": "FAILED",
                "workflow_id": workflow.id,
                "step": "TECHNICAL_V2",
                "error": str(tech_exc),
                "step_results": (workflow.meta or {}).get("step_results"),
            }
        rows_t = int(technical.get("technical_feature_rows") or technical.get("signal_rows") or 0)
        technical_payload = {
            "status": "NO_CHANGES" if rows_t == 0 else technical.get("status", "SUCCESS"),
            "rows": rows_t,
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "pin": {"code": TECHNICAL_MODEL_CODE, "version": TECHNICAL_MODEL_VERSION},
            "child_workflow_id": technical.get("workflow_id"),
        }
        _store_step(workflow, "TECHNICAL_V2", technical_payload)
        _mark(session, workflow, "TECHNICAL_V2", "SUCCESS")
        session.commit()

        # --- RELATIONS V2 (bounded latest only) ---
        _mark(session, workflow, "RELATIONS_V2", "RUNNING")
        after_market = collect_watermarks(session)
        signal_as_of = after_market.get("raw_market_latest_date")
        due, due_reason = relations_due(session, signal_as_of)
        if not due:
            relations_payload = {
                "status": "SKIPPED_NOT_DUE",
                "reason": due_reason,
                "as_of": _iso(after_market.get("relations_v2_latest_as_of")),
                "rows": 0,
                "duration_seconds": 0.0,
            }
        else:
            t0 = time.perf_counter()
            relations = RelationsComputeService(session).run_latest(
                relation_set_code=RELATIONS_CODE,
                relation_set_version=RELATIONS_VERSION,
            )
            rel_status = str(relations.get("status") or "SUCCESS").upper()
            relations_payload = {
                "status": rel_status,
                "reason": due_reason,
                "as_of": relations.get("as_of") or _iso(collect_watermarks(session).get("relations_v2_latest_as_of")),
                "rows": int(relations.get("snapshots_written") or relations.get("rows") or 0),
                "duration_seconds": round(time.perf_counter() - t0, 3),
                "child_workflow_id": relations.get("workflow_id"),
                "pin": {"code": RELATIONS_CODE, "version": RELATIONS_VERSION},
            }
        _store_step(workflow, "RELATIONS_V2", relations_payload)
        _mark(session, workflow, "RELATIONS_V2", "SUCCESS")
        session.commit()

        # --- FORWARD SIGNAL (exactly one latest eligible batch; no historical backfill) ---
        _mark(session, workflow, "FORWARD_SIGNAL", "RUNNING")
        fwd = run_forward_signal_v0(session, persist=True)
        created = fwd.status == "SUCCESS" and fwd.batch_id is not None
        forward_payload = {
            "status": fwd.status,
            "created": bool(created),
            "batch_id": fwd.batch_id,
            "as_of": _iso(fwd.as_of),
            "summary": fwd.summary,
            "historical_backfill": False,
        }
        _store_step(workflow, "FORWARD_SIGNAL", forward_payload)
        step_status = "SUCCESS"
        if fwd.status == "WARNING":
            step_status = "WARNING"
        elif fwd.status == "ERROR":
            step_status = "ERROR"
        _mark(session, workflow, "FORWARD_SIGNAL", step_status)
        session.commit()
        if fwd.status == "ERROR":
            finish_workflow(session, workflow, "FAILED", error=str((fwd.summary or {}).get("error")))
            session.commit()
            return {"status": "FAILED", "workflow_id": workflow.id, "step": "FORWARD_SIGNAL", "detail": fwd.summary}

        # --- SHADOW ADVANCE ---
        _mark(session, workflow, "SHADOW_ADVANCE", "RUNNING")
        fills_before = int(session.scalar(select(func.count()).select_from(ShadowFill)) or 0)
        orders_before = int(session.scalar(select(func.count()).select_from(ShadowOrder)) or 0)
        try:
            shadow_results = advance_all_shadow_portfolios(session)
        except Exception as shadow_exc:  # noqa: BLE001
            shadow_payload = {
                "status": "ERROR",
                "error": str(shadow_exc)[:2000],
                "fills_new": 0,
                "orders_new": 0,
                "forward_batch_id": fwd.batch_id,
            }
            _store_step(workflow, "SHADOW_ADVANCE", shadow_payload)
            _mark(session, workflow, "SHADOW_ADVANCE", "ERROR", error=str(shadow_exc)[:2000])
            session.commit()
            finish_workflow(session, workflow, "FAILED", error=f"SHADOW_ADVANCE: {shadow_exc}"[:2000])
            session.commit()
            return {
                "status": "FAILED",
                "workflow_id": workflow.id,
                "step": "SHADOW_ADVANCE",
                "error": str(shadow_exc),
                "latest_forward_batch_id": fwd.batch_id,
                "step_results": (workflow.meta or {}).get("step_results"),
            }
        fills_after = int(session.scalar(select(func.count()).select_from(ShadowFill)) or 0)
        orders_after = int(session.scalar(select(func.count()).select_from(ShadowOrder)) or 0)
        portfolios = list(session.scalars(select(ShadowPortfolio).order_by(ShadowPortfolio.id)).all())
        shadow_payload = {
            "status": "SUCCESS",
            "fills_new": fills_after - fills_before,
            "orders_new": orders_after - orders_before,
            "results": [
                {"portfolio_id": r.portfolio_id, "name": r.name, "status": r.status, **r.summary}
                for r in shadow_results
            ],
            "portfolios": [
                {
                    "id": p.id,
                    "status": p.status,
                    "cash": float(p.cash) if p.cash is not None else None,
                    "peak_nav": float(p.peak_nav) if p.peak_nav is not None else None,
                    "last_processed_market_date": _iso(p.last_processed_market_date),
                }
                for p in portfolios
            ],
        }
        _store_step(workflow, "SHADOW_ADVANCE", shadow_payload)
        _mark(session, workflow, "SHADOW_ADVANCE", "SUCCESS")
        session.commit()

        # --- PROSPECTIVE MODEL A/B (experimental; non-fatal) ---
        _mark(session, workflow, "PROSPECTIVE_MODEL_AB", "RUNNING")
        try:
            from app.modules.model_edge.application.experiment import get_experiment
            from app.modules.model_edge.application.paired_forward import run_paired_forward

            if get_experiment(session) is None:
                ab_payload: dict[str, Any] = {
                    "status": "SKIPPED",
                    "reason": "experiment_not_activated",
                    "blocks_operational_v0": False,
                }
                ab_step_status = "SUCCESS"
            else:
                paired = run_paired_forward(session, persist=True)
                ab_payload = {
                    **paired.to_dict(),
                    "blocks_operational_v0": False,
                    "historical_backfill": False,
                }
                if paired.status in {"ERROR", "PARTIAL"}:
                    ab_step_status = "WARNING"
                    ab_payload["status"] = "DEGRADED"
                else:
                    ab_step_status = "SUCCESS"
        except Exception as ab_exc:  # noqa: BLE001 — research must not fail operational cycle
            ab_payload = {
                "status": "DEGRADED",
                "error": str(ab_exc)[:2000],
                "blocks_operational_v0": False,
            }
            ab_step_status = "WARNING"
            logger.warning("PROSPECTIVE_MODEL_AB degraded: %s", ab_exc)
        _store_step(workflow, "PROSPECTIVE_MODEL_AB", ab_payload)
        _mark(session, workflow, "PROSPECTIVE_MODEL_AB", ab_step_status)
        session.commit()

        # --- PROSPECTIVE MODEL A/B SHADOW (experimental; non-fatal) ---
        _mark(session, workflow, "PROSPECTIVE_MODEL_AB_SHADOW", "RUNNING")
        try:
            from app.modules.shadow.config import MODEL_AB_EXPERIMENT_GROUP

            ab_shadow_results = advance_all_shadow_portfolios(
                session, experiment_groups=[MODEL_AB_EXPERIMENT_GROUP]
            )
            ab_shadow_payload: dict[str, Any] = {
                "status": "SUCCESS",
                "blocks_operational_v0": False,
                "results": [
                    {
                        "portfolio_id": r.portfolio_id,
                        "name": r.name,
                        "status": r.status,
                        **r.summary,
                    }
                    for r in ab_shadow_results
                ],
            }
            ab_shadow_step = "SUCCESS"
        except Exception as ab_sh_exc:  # noqa: BLE001
            ab_shadow_payload = {
                "status": "DEGRADED",
                "error": str(ab_sh_exc)[:2000],
                "blocks_operational_v0": False,
            }
            ab_shadow_step = "WARNING"
            logger.warning("PROSPECTIVE_MODEL_AB_SHADOW degraded: %s", ab_sh_exc)
        _store_step(workflow, "PROSPECTIVE_MODEL_AB_SHADOW", ab_shadow_payload)
        _mark(session, workflow, "PROSPECTIVE_MODEL_AB_SHADOW", ab_shadow_step)
        session.commit()

        # --- FORWARD OUTCOME EVALUATION ---
        _mark(session, workflow, "FORWARD_OUTCOME_EVALUATION", "RUNNING")
        outcome = evaluate_forward_outcomes(session)
        outcome_payload = {
            "status": outcome.status,
            "evaluated_new": int((outcome.summary or {}).get("evaluated_new") or 0),
            "summary": outcome.summary,
        }
        _store_step(workflow, "FORWARD_OUTCOME_EVALUATION", outcome_payload)
        _mark(session, workflow, "FORWARD_OUTCOME_EVALUATION", "SUCCESS")
        session.commit()

        # --- PROSPECTIVE MODEL A/B OUTCOME (experimental; non-fatal) ---
        _mark(session, workflow, "PROSPECTIVE_MODEL_AB_OUTCOME", "RUNNING")
        try:
            from app.modules.model_edge.application.experiment import get_experiment
            from app.modules.model_edge.application.paired_outcome import evaluate_paired_outcomes

            if get_experiment(session) is None:
                ab_out_payload: dict[str, Any] = {
                    "status": "SKIPPED",
                    "reason": "experiment_not_activated",
                    "blocks_operational_v0": False,
                }
                ab_out_step = "SUCCESS"
            else:
                paired_out = evaluate_paired_outcomes(session)
                ab_out_payload = {**paired_out.to_dict(), "blocks_operational_v0": False}
                ab_out_step = "SUCCESS"
        except Exception as ab_out_exc:  # noqa: BLE001
            ab_out_payload = {
                "status": "DEGRADED",
                "error": str(ab_out_exc)[:2000],
                "blocks_operational_v0": False,
            }
            ab_out_step = "WARNING"
            logger.warning("PROSPECTIVE_MODEL_AB_OUTCOME degraded: %s", ab_out_exc)
        _store_step(workflow, "PROSPECTIVE_MODEL_AB_OUTCOME", ab_out_payload)
        _mark(session, workflow, "PROSPECTIVE_MODEL_AB_OUTCOME", ab_out_step)
        session.commit()

        # --- FINALIZE ---
        _mark(session, workflow, "FINALIZE", "RUNNING")
        after = collect_watermarks(session)
        step_results = dict((workflow.meta or {}).get("step_results") or {})
        changed = _meaningful_change(step_results)
        final_status = "SUCCESS" if changed else "NO_CHANGES"
        # Preserve WARNING from forward gate without inventing data
        if str(forward_payload.get("status")).upper() == "WARNING" and not changed:
            final_status = "NO_CHANGES"
        # Experimental PROSPECTIVE_* stages may be WARNING without failing the cycle.
        health = determine_health(after, running=False)
        duration = round(time.perf_counter() - started, 3)
        meta = dict(workflow.meta or {})
        meta.update(
            {
                "market_watermark_after": _iso(after.get("raw_market_latest_date")),
                "watermarks_after": serialize_watermarks(after),
                "latest_forward_batch_id": after.get("forward_latest_batch_id"),
                "shadow_portfolios_affected": [p.id for p in portfolios],
                "forward_outcomes_evaluated": outcome_payload.get("evaluated_new"),
                "health": health,
                "duration_seconds": duration,
                "changed": changed,
            }
        )
        workflow.meta = meta
        flag_modified(workflow, "meta")
        finalize_payload = {
            "status": final_status,
            "health": health,
            "duration_seconds": duration,
            "changed": changed,
        }
        _store_step(workflow, "FINALIZE", finalize_payload)
        _mark(session, workflow, "FINALIZE", "SUCCESS")
        finish_workflow(session, workflow, final_status)
        session.commit()

        return {
            "status": final_status,
            "workflow_id": workflow.id,
            "health": health,
            "duration_seconds": duration,
            "watermarks_before": serialize_watermarks(before),
            "watermarks_after": serialize_watermarks(after),
            "step_results": (workflow.meta or {}).get("step_results"),
            "latest_forward_batch_id": after.get("forward_latest_batch_id"),
            "operational": build_operational_status(session),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("daily_research_cycle_failed", extra={"error": str(exc)})
        session.rollback()
        if workflow is not None:
            try:
                wf = session.get(Workflow, workflow.id)
                if wf is not None:
                    finish_workflow(session, wf, "FAILED", error=str(exc)[:2000])
                    session.commit()
            except Exception:
                session.rollback()
        return {"status": "FAILED", "error": str(exc), "workflow_id": workflow.id if workflow else None}
    finally:
        lock.release()
