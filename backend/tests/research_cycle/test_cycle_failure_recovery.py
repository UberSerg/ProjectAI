"""Integration: mid-cycle failure + retry without duplicating Forward/Shadow/upstream rows."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Workflow
from app.modules.prediction.application.forward_outcome import OutcomeEvalResult
from app.modules.prediction.application.forward_runner import ForwardRunResult
from app.modules.research_cycle.config import CYCLE_WORKFLOW_TYPE
from app.modules.research_cycle.cycle import run_daily_research_cycle
from app.modules.shadow.application.service import AdvanceResult


def _lock_ok(token: str, *, ttl: int = 0) -> MagicMock:
    handle = MagicMock()
    handle.acquired = True
    handle.release = MagicMock()
    return handle


def _bind_flush_only(session: Session) -> None:
    """Keep cycle checkpoints inside the outer test transaction (no live DB pollution)."""

    def _commit() -> None:
        session.flush()

    def _rollback() -> None:
        # Do not undo already-flushed upstream steps inside the test transaction.
        session.expire_all()

    session.commit = _commit  # type: ignore[method-assign]
    session.rollback = _rollback  # type: ignore[method-assign]


@pytest.fixture
def recovery_harness(core_db: Session):
    """Patched Daily Research Cycle services with deterministic injectable failures."""
    _bind_flush_only(core_db)

    state: dict = {
        "candle_keys": set(),
        "analytics_keys": set(),
        "technical_keys": set(),
        "market_calls": 0,
        "analytics_calls": 0,
        "technical_calls": 0,
        "relations_calls": 0,
        "forward_calls": 0,
        "shadow_calls": 0,
        "outcome_calls": 0,
        "forward_batch_id": None,
        "fail_technical": True,
        "fail_shadow": False,
        "shadow_advanced": 0,
        "outcomes_created": 0,
    }

    def market_update(self, *, workflow_id=None):  # noqa: ANN001
        state["market_calls"] += 1
        key = "candle:TEST:2026-09-10"
        inserted = 0
        if key not in state["candle_keys"]:
            state["candle_keys"].add(key)
            inserted = 1
        return {
            "status": "SUCCESS",
            "stats": {"received": 1, "inserted": inserted, "updated": 0, "rejected": 0, "warnings": 0},
            "workflow_id": None,
        }

    def ca_run(self, *, workflow_id=None):  # noqa: ANN001
        return {"status": "NO_CHANGES", "inserted": 0, "updated": 0, "workflow_id": None}

    def analytics_update(  # noqa: ANN001
        self, *, feature_set_code="basic_daily", feature_set_version=2, workflow_id=None
    ):
        state["analytics_calls"] += 1
        key = f"analytics:{feature_set_code}:{feature_set_version}:2026-09-10"
        rows = 0
        if key not in state["analytics_keys"]:
            state["analytics_keys"].add(key)
            rows = 7
        return {
            "status": "SUCCESS" if rows else "NO_CHANGES",
            "instrument_rows": rows,
            "series_rows": 0,
            "workflow_id": None,
        }

    def technical_update(self, *, model_code="rules", model_version=2, workflow_id=None):  # noqa: ANN001
        state["technical_calls"] += 1
        if state["fail_technical"]:
            raise RuntimeError("INJECTED_TECHNICAL_FAILURE")
        key = f"technical:{model_code}:{model_version}:2026-09-10"
        rows = 0
        if key not in state["technical_keys"]:
            state["technical_keys"].add(key)
            rows = 4
        return {
            "status": "SUCCESS" if rows else "NO_CHANGES",
            "technical_feature_rows": rows,
            "signal_rows": rows,
            "workflow_id": None,
        }

    def relations_latest(  # noqa: ANN001
        self, *, relation_set_code="basic_relations", relation_set_version=2, workflow_id=None
    ):
        state["relations_calls"] += 1
        return {"status": "NO_CHANGES", "snapshots_written": 0, "as_of": "2026-09-10", "workflow_id": None}

    def forward_run(session, *, as_of=None, persist=True, **_kwargs):  # noqa: ANN001
        state["forward_calls"] += 1
        if state["forward_batch_id"] is None:
            state["forward_batch_id"] = 91001
            return ForwardRunResult(
                status="SUCCESS",
                batch_id=state["forward_batch_id"],
                as_of=date(2026, 9, 10),
                summary={"created": True, "eligible_count": 3},
            )
        return ForwardRunResult(
            status="NO_CHANGES",
            batch_id=state["forward_batch_id"],
            as_of=date(2026, 9, 10),
            summary={"created": False, "reason": "already_frozen"},
        )

    def shadow_advance(session, *, clock=None):  # noqa: ANN001
        state["shadow_calls"] += 1
        if state["fail_shadow"]:
            raise RuntimeError("INJECTED_SHADOW_FAILURE")
        state["shadow_advanced"] += 1
        return [
            AdvanceResult(
                portfolio_id=1,
                name="SHADOW_HYSTERESIS_V1",
                status="WAITING_FOR_FUTURE_MARKET_OPEN",
                summary={"decisions_created": 0, "orders_created": 0, "fills": 0},
            )
        ]

    def outcome_eval(session, *, batch_id=None):  # noqa: ANN001
        state["outcome_calls"] += 1
        created = 0
        if state["outcomes_created"] == 0:
            created = 3
            state["outcomes_created"] = created
        return OutcomeEvalResult(
            status="SUCCESS" if created else "NO_CHANGES",
            summary={"evaluated_new": created, "batches": []},
        )

    def _wm_refresh(*_a, **_k):
        return {
            "raw_market_latest_date": "2026-09-10",
            "analytics_v2_latest_date": "2026-09-10",
            "technical_v2_latest_date": "2026-09-10" if state["technical_keys"] else "2026-09-09",
            "relations_v2_latest_as_of": "2026-09-10",
            "forward_latest_as_of": "2026-09-10" if state["forward_batch_id"] else None,
            "forward_latest_generated_at": None,
            "forward_latest_batch_id": state["forward_batch_id"],
            "shadow_portfolios": [],
            "forward_outcome_latest_status": None,
            "forward_outcome_latest_evaluated_at": None,
            "max_relation_age_days": 8,
            "technical_model_pin": {"code": "rules", "version": 2},
        }

    patches = [
        patch("app.modules.research_cycle.cycle.try_acquire_cycle_lock", side_effect=_lock_ok),
        patch("app.modules.research_cycle.cycle.collect_watermarks", side_effect=_wm_refresh),
        patch("app.modules.research_cycle.cycle.relations_due", return_value=(False, "SKIPPED_NOT_DUE")),
        patch("app.modules.research_cycle.cycle.serialize_watermarks", side_effect=lambda wm: wm),
        patch("app.modules.research_cycle.cycle.determine_health", return_value="IN_SYNC"),
        patch("app.modules.research_cycle.cycle.build_operational_status", return_value={"health": "IN_SYNC"}),
        patch("app.modules.research_cycle.cycle.MarketIngestionService.run_update", market_update),
        patch("app.modules.research_cycle.cycle.SplitIngestionService.run", ca_run),
        patch("app.modules.research_cycle.cycle.FeatureComputeService.run_update", analytics_update),
        patch("app.modules.research_cycle.cycle.TechnicalComputeService.run_update", technical_update),
        patch("app.modules.research_cycle.cycle.RelationsComputeService.run_latest", relations_latest),
        patch("app.modules.research_cycle.cycle.run_forward_signal_v0", side_effect=forward_run),
        patch("app.modules.research_cycle.cycle.advance_all_shadow_portfolios", side_effect=shadow_advance),
        patch("app.modules.research_cycle.cycle.evaluate_forward_outcomes", side_effect=outcome_eval),
    ]
    for p in patches:
        p.start()

    yield core_db, state

    for p in patches:
        p.stop()


def test_mid_cycle_technical_failure_then_recovery(recovery_harness) -> None:
    session, state = recovery_harness

    first = run_daily_research_cycle(session)
    assert first["status"] == "FAILED"
    assert first["step"] == "TECHNICAL_V2"
    assert "INJECTED_TECHNICAL_FAILURE" in str(first.get("error"))

    steps = first.get("step_results") or {}
    assert steps["MARKET_UPDATE"]["status"] == "SUCCESS"
    assert steps["MARKET_UPDATE"]["stats"]["inserted"] == 1
    assert steps["CBR_UPDATE"]["status"] == "SUCCESS"
    assert steps["CORPORATE_ACTION_UPDATE"]["status"] == "NO_CHANGES"
    assert steps["ANALYTICS_V2"]["status"] in {"SUCCESS", "NO_CHANGES"}
    assert int(steps["ANALYTICS_V2"].get("rows") or 0) == 7
    assert steps["TECHNICAL_V2"]["status"] == "ERROR"
    assert "FORWARD_SIGNAL" not in steps
    assert "SHADOW_ADVANCE" not in steps
    assert "FORWARD_OUTCOME_EVALUATION" not in steps

    assert state["forward_calls"] == 0
    assert state["shadow_calls"] == 0
    assert state["outcome_calls"] == 0
    assert state["forward_batch_id"] is None
    assert len(state["candle_keys"]) == 1
    assert len(state["analytics_keys"]) == 1
    assert len(state["technical_keys"]) == 0

    failed_wf = session.get(Workflow, first["workflow_id"])
    assert failed_wf is not None
    assert failed_wf.workflow_type == CYCLE_WORKFLOW_TYPE
    assert str(failed_wf.status).upper() == "FAILED"
    tech_step = next(s for s in failed_wf.steps if s.name == "TECHNICAL_V2")
    assert tech_step.status == "ERROR"

    # Recovery: remove injected failure and rerun
    state["fail_technical"] = False
    second = run_daily_research_cycle(session)
    assert second["status"] in {"SUCCESS", "NO_CHANGES"}
    assert second["workflow_id"] != first["workflow_id"]

    steps2 = second.get("step_results") or {}
    assert steps2["MARKET_UPDATE"]["stats"]["inserted"] == 0
    assert int(steps2["ANALYTICS_V2"].get("rows") or 0) == 0
    assert steps2["TECHNICAL_V2"]["status"] in {"SUCCESS", "NO_CHANGES"}
    assert int(steps2["TECHNICAL_V2"].get("rows") or 0) == 4
    assert steps2["RELATIONS_V2"]["status"] == "SKIPPED_NOT_DUE"
    assert steps2["FORWARD_SIGNAL"]["created"] is True
    assert steps2["FORWARD_SIGNAL"]["batch_id"] == 91001
    assert steps2["SHADOW_ADVANCE"]["status"] == "SUCCESS"
    assert steps2["FORWARD_OUTCOME_EVALUATION"]["status"] in {"SUCCESS", "NO_CHANGES"}

    assert state["market_calls"] == 2
    assert len(state["candle_keys"]) == 1
    assert len(state["analytics_keys"]) == 1
    assert len(state["technical_keys"]) == 1
    assert state["forward_calls"] == 1
    assert state["shadow_calls"] == 1
    assert state["shadow_advanced"] == 1
    assert state["outcome_calls"] == 1
    assert state["outcomes_created"] == 3

    ok_wf = session.get(Workflow, second["workflow_id"])
    assert ok_wf is not None
    assert str(ok_wf.status).upper() in {"SUCCESS", "NO_CHANGES"}


def test_failure_after_forward_reuses_batch_on_retry(recovery_harness) -> None:
    session, state = recovery_harness
    state["fail_technical"] = False
    state["fail_shadow"] = True

    first = run_daily_research_cycle(session)
    assert first["status"] == "FAILED"
    assert first["step"] == "SHADOW_ADVANCE"
    assert first.get("latest_forward_batch_id") == 91001
    steps = first.get("step_results") or {}
    assert steps["FORWARD_SIGNAL"]["created"] is True
    assert steps["FORWARD_SIGNAL"]["batch_id"] == 91001
    assert steps["SHADOW_ADVANCE"]["status"] == "ERROR"
    assert "FORWARD_OUTCOME_EVALUATION" not in steps
    assert state["forward_calls"] == 1
    assert state["shadow_advanced"] == 0
    assert state["outcome_calls"] == 0

    state["fail_shadow"] = False
    second = run_daily_research_cycle(session)
    assert second["status"] in {"SUCCESS", "NO_CHANGES"}
    steps2 = second.get("step_results") or {}
    assert steps2["FORWARD_SIGNAL"]["created"] is False
    assert steps2["FORWARD_SIGNAL"]["status"] == "NO_CHANGES"
    assert steps2["FORWARD_SIGNAL"]["batch_id"] == 91001
    assert steps2["SHADOW_ADVANCE"]["status"] == "SUCCESS"
    assert state["forward_calls"] == 2
    assert state["forward_batch_id"] == 91001
    assert state["shadow_advanced"] == 1
    assert state["outcome_calls"] == 1
    assert len(state["candle_keys"]) == 1
    assert len(state["analytics_keys"]) == 1
    assert len(state["technical_keys"]) == 1
