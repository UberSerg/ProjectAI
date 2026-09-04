"""API read-model tests for Simulator Dashboard."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.modules.simulator.application.dashboard_read import imoex_benchmark_series
from app.modules.simulator.infrastructure.models import SimulationRun, SimulationSpec
from app.modules.simulator.infrastructure.repository import run_to_summary


def test_run_to_summary_includes_spec(core_db: Session) -> None:
    spec = SimulationSpec(
        config_hash="abc123",
        segment="FINAL_HOLDOUT",
        policy_name="RANK_LONG_ONLY_V0",
        payload={
            "commission_bps": 5.0,
            "slippage_bps": 0.0,
            "cost_sensitivity_label": "COST_SENSITIVITY_5bps",
            "policy_name": "RANK_LONG_ONLY_V0",
            "initial_capital": 1_000_000,
        },
    )
    core_db.add(spec)
    core_db.flush()
    run = SimulationRun(
        simulation_spec_id=spec.id,
        status="SUCCESS",
        segment="FINAL_HOLDOUT",
        date_from=date(2026, 1, 5),
        date_to=date(2026, 8, 6),
        metrics={"total_price_return": -0.06, "final_nav": 940000},
        benchmark={"total_price_return": -0.17},
    )
    core_db.add(run)
    core_db.flush()
    summary = run_to_summary(core_db, run)
    assert summary["engineering_status"] == "PASS"
    assert summary["spec"]["commission_bps"] == 5.0
    assert summary["spec"]["cost_sensitivity_label"] == "COST_SENSITIVITY_5bps"
    assert summary["spec"]["policy_name"] == "RANK_LONG_ONLY_V0"


def test_imoex_benchmark_series_empty_without_instrument(core_db: Session) -> None:
    series = imoex_benchmark_series(
        core_db, date_from=date(2026, 1, 1), date_to=date(2026, 1, 10)
    )
    assert isinstance(series, list)
