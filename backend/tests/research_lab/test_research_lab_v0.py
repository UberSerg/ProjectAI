"""Simulator Research Lab V0 — backend tests (validation, reuse, compare, suite)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.modules.research_lab.application.compare import compare_runs
from app.modules.research_lab.application.service import (
    config_hash_ignores_note,
    fingerprint_excluding_cost,
    launch_research_run,
    plan_quick_suite,
    preview_config_hash,
    research_options,
)
from app.modules.research_lab.catalog import (
    ALLOWED_RESEARCH_SEGMENT,
    PROTECTED_SEGMENT,
    QUICK_SUITE_VARIANTS,
    resolve_policy_risk_kwargs,
)
from app.modules.research_lab.errors import (
    HoldoutLaunchForbidden,
    InvalidCapital,
    InvalidCost,
    PeriodOutsideDev,
    UnknownCandidate,
    UnknownPolicy,
    UnknownRisk,
)
from app.modules.simulator.config import (
    POLICY_HYSTERESIS_V1,
    POLICY_NAME,
    RISK_DD_GUARD_V1,
    RISK_NAME,
    SimulationSpecV0,
)


def _body(**overrides: Any) -> dict[str, Any]:
    base = {
        "candidate_id": "prediction_ml_candidate/v0",
        "segment": ALLOWED_RESEARCH_SEGMENT,
        "policy_id": POLICY_HYSTERESIS_V1,
        "risk_id": RISK_NAME,
        "commission_bps": 10.0,
        "date_from": "2023-01-01",
        "date_to": "2024-12-31",
        "initial_capital": 1_000_000.0,
    }
    base.update(overrides)
    return base


@pytest.fixture
def mock_dev_bounds():
    with patch(
        "app.modules.research_lab.application.service._dev_bounds",
        return_value=(date(2017, 2, 1), date(2026, 1, 5)),
    ):
        yield


@pytest.fixture
def mock_bundle_preview():
    bundle = SimpleNamespace(
        prediction_hash="pred_hash",
        candidate_config_hash="cand_hash",
        dataset_values_hash="ds_hash",
        candidate_name="prediction_ml_candidate",
        candidate_version="v0",
        prediction_semantic="EXPECTED_RETURN",
    )
    with patch(
        "app.modules.research_lab.application.service.load_oos_predictions",
        return_value=bundle,
    ):
        yield bundle


def test_options_lists_catalog(mock_dev_bounds) -> None:
    with patch(
        "app.modules.research_lab.application.service.describe_ready",
        return_value={},
    ):
        opts = research_options()
    assert any(c["candidate_version"] == "v0" for c in opts["candidates"])
    segs = {s["id"]: s for s in opts["prediction_segments"]}
    assert segs[ALLOWED_RESEARCH_SEGMENT]["launchable"] is True
    assert segs[PROTECTED_SEGMENT]["launchable"] is False
    assert len(opts["policies"]) >= 2
    assert len(opts["risk_policies"]) >= 2
    assert [p["bps"] for p in opts["cost_presets"]] == [0.0, 5.0, 10.0, 20.0]


def test_holdout_launch_rejected(mock_dev_bounds) -> None:
    session = MagicMock()
    with pytest.raises(HoldoutLaunchForbidden) as ei:
        launch_research_run(session, _body(segment=PROTECTED_SEGMENT))
    assert ei.value.code == "HOLDOUT_LAUNCH_FORBIDDEN"


def test_unknown_candidate_rejected(mock_dev_bounds) -> None:
    session = MagicMock()
    with pytest.raises(UnknownCandidate):
        launch_research_run(session, _body(candidate_id="no_such_model/v9"))


def test_unknown_policy_rejected(mock_dev_bounds) -> None:
    with pytest.raises(UnknownPolicy):
        resolve_policy_risk_kwargs("NOT_A_POLICY", RISK_NAME)


def test_unknown_risk_rejected(mock_dev_bounds) -> None:
    with pytest.raises(UnknownRisk):
        resolve_policy_risk_kwargs(POLICY_NAME, "NOT_A_RISK")


def test_period_outside_dev_rejected(mock_dev_bounds) -> None:
    session = MagicMock()
    with pytest.raises(PeriodOutsideDev):
        launch_research_run(
            session, _body(date_from="2010-01-01", date_to="2010-06-01")
        )


def test_negative_capital_rejected(mock_dev_bounds) -> None:
    session = MagicMock()
    with pytest.raises(InvalidCapital):
        launch_research_run(session, _body(initial_capital=-1))


def test_negative_cost_rejected(mock_dev_bounds) -> None:
    session = MagicMock()
    with pytest.raises(InvalidCost):
        launch_research_run(session, _body(commission_bps=-5))


def test_note_does_not_alter_config_hash(mock_dev_bounds, mock_bundle_preview) -> None:
    out = config_hash_ignores_note(
        MagicMock(),
        _body(),
    )
    assert out["equal"] is True
    assert out["hash_without_note"] == out["hash_with_note"]


def test_preview_preserves_hashes(mock_dev_bounds, mock_bundle_preview) -> None:
    from app.modules.research_lab.application.service import _validate_launch_request

    validated = _validate_launch_request(_body())
    spec, config_hash, family = preview_config_hash(validated)
    assert spec.prediction_hash == "pred_hash"
    assert spec.candidate_config_hash == "cand_hash"
    assert spec.dataset_values_hash == "ds_hash"
    assert spec.policy_name == POLICY_HYSTERESIS_V1
    assert spec.risk_name == RISK_NAME
    assert len(config_hash) == 64
    assert len(family) == 64
    assert family == fingerprint_excluding_cost(spec)


def test_reuse_existing_success(mock_dev_bounds, mock_bundle_preview) -> None:
    session = MagicMock()
    existing = SimpleNamespace(
        id=42,
        status="SUCCESS",
        segment=ALLOWED_RESEARCH_SEGMENT,
        simulation_spec_id=1,
        date_from=date(2023, 1, 3),
        date_to=date(2024, 12, 28),
        candidate_config_hash="cand_hash",
        dataset_values_hash="ds_hash",
        prediction_hash="pred_hash",
        values_hash="vh",
        metrics={"total_price_return": 0.1},
        benchmark={},
        provenance={
            "research_lab": {
                "requested_date_from": "2023-01-01",
                "requested_date_to": "2024-12-31",
                "display_name": "Existing",
            }
        },
        created_at=None,
    )

    with (
        patch(
            "app.modules.research_lab.application.service._find_reusable_run",
            return_value=existing,
        ),
        patch(
            "app.modules.research_lab.application.service.enrich_run_summary",
            return_value={"id": 42, "status": "SUCCESS"},
        ),
        patch(
            "app.modules.research_lab.application.service.run_segment"
        ) as run_seg,
    ):
        out = launch_research_run(session, _body())
        run_seg.assert_not_called()
        assert out["outcome"] == "REUSE_EXISTING"
        assert out["simulation_executed"] is False
        assert out["run"]["id"] == 42


def test_create_calls_run_segment_not_fit(mock_dev_bounds, mock_bundle_preview) -> None:
    session = MagicMock()
    fake_run = SimpleNamespace(
        id=99,
        provenance={},
        status="SUCCESS",
        segment=ALLOWED_RESEARCH_SEGMENT,
        simulation_spec_id=1,
    )
    fake_result = SimpleNamespace(
        config_hash="abc",
        metrics={"total_price_return": 0.05},
        spec=SimpleNamespace(initial_capital=1_000_000.0),
    )

    with (
        patch(
            "app.modules.research_lab.application.service._find_reusable_run",
            return_value=None,
        ),
        patch(
            "app.modules.research_lab.application.service.run_segment",
            return_value=(fake_result, 99),
        ) as run_seg,
        patch(
            "app.modules.research_lab.application.service.get_run",
            return_value=fake_run,
        ),
        patch(
            "app.modules.research_lab.application.service.enrich_run_summary",
            return_value={"id": 99, "status": "SUCCESS"},
        ),
    ):
        out = launch_research_run(session, _body(name="Lab · test", note="note only"))
        run_seg.assert_called_once()
        kwargs = run_seg.call_args.kwargs
        assert kwargs.get("persist") is True
        assert run_seg.call_args.args[1] == "DEVELOPMENT_OOS"
        assert out["simulation_executed"] is True
        assert fake_run.provenance["research_lab"]["note"] == "note only"
        assert fake_run.provenance["research_lab"]["created_from"] == "RESEARCH_LAB"


def test_cost_family_fingerprint_ignores_cost() -> None:
    from app.modules.simulator.config import hysteresis_v1_spec_kwargs

    base = {
        "segment": "DEVELOPMENT_OOS",
        "prediction_hash": "p",
        "candidate_config_hash": "c",
        "dataset_values_hash": "d",
        **hysteresis_v1_spec_kwargs(),
    }
    a = SimulationSpecV0(**{**base, "commission_bps": 0.0})
    b = SimulationSpecV0(
        **{
            **base,
            "commission_bps": 20.0,
            "cost_sensitivity_label": "COST_SENSITIVITY_20bps",
        }
    )
    assert fingerprint_excluding_cost(a) == fingerprint_excluding_cost(b)
    assert a.config_hash() != b.config_hash()


def test_compare_fair_and_differences() -> None:
    def _ctx(run_id: int, *, policy: str, bps: float, segment: str = "DEVELOPMENT_OOS"):
        run = SimpleNamespace(
            id=run_id,
            status="SUCCESS",
            segment=segment,
            simulation_spec_id=run_id,
            date_from=date(2023, 1, 1),
            date_to=date(2024, 12, 31),
            candidate_config_hash="same",
            metrics={
                "total_price_return": 0.1 * run_id,
                "cagr": 0.05,
                "max_drawdown": -0.2,
                "turnover_ratio": 10.0 * run_id,
                "sharpe_rf0": 0.3,
                "trade_count": 100,
                "annualized_volatility": 0.2,
                "average_gross_exposure": 0.9,
                "average_cash_weight": 0.1,
                "excess_vs_imoex": 0.05,
            },
            benchmark={"total_price_return": -0.1},
            provenance={},
        )
        payload = {
            "policy_name": policy,
            "risk_name": RISK_NAME,
            "commission_bps": bps,
            "initial_capital": 1_000_000.0,
            "execution_timing": "next_open",
            "fractional_shares": True,
        }
        summary = {
            "id": run_id,
            "segment": segment,
            "spec": payload,
            "metrics": run.metrics,
            "research": {"display_name": f"E{run_id}", "observed_holdout": segment == "FINAL_HOLDOUT"},
        }
        return run, payload, summary

    runs_data = [
        _ctx(1, policy=POLICY_NAME, bps=0.0),
        _ctx(2, policy=POLICY_HYSTERESIS_V1, bps=0.0),
        _ctx(3, policy=POLICY_HYSTERESIS_V1, bps=0.0, segment="FINAL_HOLDOUT"),
    ]

    session = MagicMock()

    with (
        patch(
            "app.modules.research_lab.application.compare.get_run",
            side_effect=lambda _s, rid: runs_data[rid - 1][0],
        ),
        patch(
            "app.modules.research_lab.application.compare.enrich_run_summary",
            side_effect=lambda _s, run: runs_data[run.id - 1][2],
        ),
        patch(
            "app.modules.research_lab.application.compare.get_nav_series",
            return_value=[],
        ),
    ):
        def session_get(_cls, sid):
            return SimpleNamespace(payload=runs_data[sid - 1][1])

        session.get.side_effect = session_get
        out = compare_runs(session, [1, 2, 3])

    assert out["fair_comparison"] is False
    assert out["fair_badge"] == "Условия различаются"
    assert out["model_comparison"] is False
    assert out["observed_holdout_warning"]
    assert len(out["metrics_table"]) >= 5
    assert len(out["runs"]) == 3


def test_compare_fair_when_only_candidate_differs() -> None:
    """V0 vs V1 model A/B: same period/policy/risk/cost → fair_comparison + model_comparison."""

    def _ctx(run_id: int, *, candidate_hash: str):
        run = SimpleNamespace(
            id=run_id,
            status="SUCCESS",
            segment="DEVELOPMENT_OOS",
            simulation_spec_id=run_id,
            date_from=date(2023, 1, 1),
            date_to=date(2024, 12, 31),
            candidate_config_hash=candidate_hash,
            metrics={
                "total_price_return": 0.1,
                "cagr": 0.05,
                "max_drawdown": -0.2,
                "turnover_ratio": 8.0,
                "sharpe_rf0": 0.3,
                "trade_count": 100,
                "annualized_volatility": 0.2,
                "average_gross_exposure": 0.9,
                "average_cash_weight": 0.1,
                "excess_vs_imoex": 0.05,
            },
            benchmark={"total_price_return": -0.1},
            provenance={},
        )
        payload = {
            "policy_name": POLICY_HYSTERESIS_V1,
            "risk_name": RISK_NAME,
            "commission_bps": 10.0,
            "initial_capital": 1_000_000.0,
            "execution_timing": "next_open",
            "fractional_shares": True,
        }
        summary = {
            "id": run_id,
            "segment": "DEVELOPMENT_OOS",
            "spec": payload,
            "metrics": run.metrics,
            "research": {"display_name": f"E{run_id}", "observed_holdout": False},
        }
        return run, payload, summary

    runs_data = [
        _ctx(1, candidate_hash="cand_v0"),
        _ctx(2, candidate_hash="cand_v1"),
    ]
    session = MagicMock()

    with (
        patch(
            "app.modules.research_lab.application.compare.get_run",
            side_effect=lambda _s, rid: runs_data[rid - 1][0],
        ),
        patch(
            "app.modules.research_lab.application.compare.enrich_run_summary",
            side_effect=lambda _s, run: runs_data[run.id - 1][2],
        ),
        patch(
            "app.modules.research_lab.application.compare.get_nav_series",
            return_value=[],
        ),
    ):
        def session_get(_cls, sid):
            return SimpleNamespace(payload=runs_data[sid - 1][1])

        session.get.side_effect = session_get
        out = compare_runs(session, [1, 2])

    assert out["fair_comparison"] is True
    assert out["fair_badge"] == "Сопоставимые условия"
    assert out["model_comparison"] is True
    assert out["differences"] == []
    assert any("разные модели" in line for line in out["interpretation"])


def test_quick_suite_bounded(mock_dev_bounds, mock_bundle_preview) -> None:
    session = MagicMock()
    with patch(
        "app.modules.research_lab.application.service._find_reusable_run",
        return_value=None,
    ):
        plan = plan_quick_suite(session, {"date_from": "2023-01-01", "date_to": "2024-12-31"})
    assert plan["total"] == len(QUICK_SUITE_VARIANTS) * 4
    assert plan["total"] <= 12
    assert plan["not_optimization"] is True
    assert plan["will_run"] == plan["total"]


def test_policy_risk_versions_in_kwargs() -> None:
    kw = resolve_policy_risk_kwargs(POLICY_HYSTERESIS_V1, RISK_DD_GUARD_V1)
    assert kw["policy_name"] == POLICY_HYSTERESIS_V1
    assert kw["risk_name"] == RISK_DD_GUARD_V1
    assert kw["entry_quantile"] == 0.20
    assert kw["dd_trigger"] == -0.20
