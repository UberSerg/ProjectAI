"""Focused tests for Intelligence Risk + Scenario Engine V1."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.modules.intelligence.contracts.risk import RiskAssessmentV1
from app.modules.intelligence.risk.constants import (
    ENGINE_ID,
    ENGINE_VERSION,
    LIMITATION_NO_CRASH_ODDS,
    LIMITATION_NOT_FORECAST,
    SCENARIO_COST_WIDEN,
    SCENARIO_PRICE_M10,
    SCENARIO_PRICE_M20,
    SCENARIO_SECTOR_DD,
    SCENARIO_VOL_SHOCK,
)
from app.modules.intelligence.risk.engine import RiskScenarioEngine, assess_risk
from app.modules.intelligence.risk.inputs import RiskFactorInputs
from app.modules.intelligence.risk.persistence import (
    persist_risk_assessment,
    risk_assessments_schema_ready,
)
from app.modules.intelligence.risk.scenarios import build_stress_scenarios
from app.modules.risk import __doc__ as modules_risk_doc


def _full_inputs(**overrides: object) -> RiskFactorInputs:
    base = dict(
        as_of=date(2026, 10, 1),
        instrument_id=42,
        realized_vol=0.22,
        atr_pct=0.02,
        drawdown=-0.08,
        avg_daily_value=80_000_000.0,
        spread_proxy_bps=15.0,
        market_regime="NEUTRAL",
        event_risk_level="NONE",
        material_adverse_event=False,
        ca_uncertainty="NONE",
        fundamental_deterioration="NONE",
        data_stale=False,
        data_missing_critical=False,
        stale_days=1,
        position_weight=0.05,
        position_nav=1_000_000.0,
    )
    base.update(overrides)
    return RiskFactorInputs(**base)  # type: ignore[arg-type]


def test_assess_risk_moderate_profile() -> None:
    assessment = assess_risk(_full_inputs())
    assert isinstance(assessment, RiskAssessmentV1)
    assert assessment.instrument_id == 42
    assert assessment.risk_state in {"LOW", "MODERATE", "ELEVATED", "HIGH"}
    assert assessment.risk_score is not None
    assert 0.0 <= assessment.risk_score <= 1.0
    assert assessment.metadata["engine_id"] == ENGINE_ID
    assert assessment.metadata["engine_version"] == ENGINE_VERSION
    assert LIMITATION_NOT_FORECAST in assessment.limitations
    assert LIMITATION_NO_CRASH_ODDS in assessment.limitations


def test_missing_inputs_are_not_treated_as_zero_safe() -> None:
    sparse = RiskFactorInputs(as_of=date(2026, 10, 1), instrument_id=1)
    assessment = assess_risk(sparse)
    assert "volatility_missing" in assessment.risk_flags
    assert "liquidity_missing" in assessment.risk_flags
    assert assessment.data_risk in {"UNKNOWN", "ELEVATED", "HIGH"}
    # Sparse UNKNOWN-heavy profile must not collapse to LOW by fabricating safety.
    assert assessment.risk_state != "LOW"


def test_material_adverse_event_forces_high() -> None:
    assessment = assess_risk(_full_inputs(material_adverse_event=True, event_risk_level="LOW"))
    assert assessment.risk_state == "HIGH"
    assert "material_adverse_event" in assessment.risk_flags
    assert assessment.risk_score is not None
    assert assessment.risk_score >= 0.85


def test_high_vol_and_deep_drawdown_elevate() -> None:
    calm = assess_risk(_full_inputs(realized_vol=0.10, atr_pct=0.01, drawdown=-0.02))
    stressed = assess_risk(
        _full_inputs(realized_vol=0.55, atr_pct=0.06, drawdown=-0.28, market_regime="STRESS")
    )
    assert calm.risk_score is not None and stressed.risk_score is not None
    assert stressed.risk_score > calm.risk_score
    assert stressed.risk_state in {"ELEVATED", "HIGH"}
    assert "elevated_volatility" in stressed.risk_flags
    assert "deep_drawdown" in stressed.risk_flags


def test_concentration_flag_with_portfolio_context() -> None:
    assessment = assess_risk(_full_inputs(position_weight=0.18))
    assert assessment.concentration_risk == "HIGH"
    assert "high_concentration" in assessment.risk_flags


def test_deterministic_stress_scenarios() -> None:
    scenarios = build_stress_scenarios(_full_inputs(position_nav=2_000_000.0))
    by_id = {s.scenario_id: s for s in scenarios}
    assert set(by_id) == {
        SCENARIO_PRICE_M10,
        SCENARIO_PRICE_M20,
        SCENARIO_VOL_SHOCK,
        SCENARIO_COST_WIDEN,
        SCENARIO_SECTOR_DD,
    }
    assert by_id[SCENARIO_PRICE_M10].price_shock == pytest.approx(-0.10)
    assert by_id[SCENARIO_PRICE_M10].nav_impact == pytest.approx(-200_000.0)
    assert by_id[SCENARIO_PRICE_M20].price_shock == pytest.approx(-0.20)
    assert by_id[SCENARIO_PRICE_M20].nav_impact == pytest.approx(-400_000.0)
    assert by_id[SCENARIO_VOL_SHOCK].price_shock is None
    assert "not a probability" in " ".join(by_id[SCENARIO_VOL_SHOCK].notes).lower()
    # No fabricated crash odds language in scenario descriptions.
    joined = " ".join(s.description.lower() for s in scenarios)
    assert "probability" not in joined
    assert "% chance" not in joined


def test_scenarios_without_nav_use_fractional_impact() -> None:
    scenarios = build_stress_scenarios(
        RiskFactorInputs(as_of=date(2026, 10, 1), instrument_id=7, atr_pct=0.02)
    )
    m10 = next(s for s in scenarios if s.scenario_id == SCENARIO_PRICE_M10)
    assert m10.nav_impact == pytest.approx(-0.10)


def test_engine_wrapper_and_roundtrip_dict() -> None:
    engine = RiskScenarioEngine()
    assessment = engine.assess(_full_inputs())
    payload = assessment.to_dict()
    assert payload["risk_state"] == assessment.risk_state
    assert len(payload["scenarios"]) == 5
    assert payload["metadata"]["engine_id"] == ENGINE_ID


def test_persist_skips_when_schema_missing() -> None:
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = False
    assessment = assess_risk(_full_inputs())
    result = persist_risk_assessment(session, assessment)
    assert result.persisted is False
    assert result.reason == "schema_not_ready"
    assert risk_assessments_schema_ready(session) is False


def test_persist_upserts_when_schema_ready() -> None:
    session = MagicMock()
    # First call: schema check True; second: INSERT.
    session.execute.return_value.scalar_one.return_value = True
    assessment = assess_risk(_full_inputs())
    result = persist_risk_assessment(session, assessment)
    assert result.persisted is True
    assert result.reason == "upserted"
    assert session.execute.call_count >= 2


def test_modules_risk_boundary_untouched() -> None:
    # Product risk package remains an empty boundary placeholder.
    assert modules_risk_doc is not None
    assert "intentionally empty" in (modules_risk_doc or "").lower()
