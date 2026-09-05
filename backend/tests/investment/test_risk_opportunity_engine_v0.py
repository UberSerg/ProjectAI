"""Risk & Opportunity Engine V0 tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.investment.domain.calibration import (
    CalibrationStatus,
    calibrate_equity_predictions,
)
from app.modules.investment.domain.decision_engine import (
    InvestmentDecisionEngine,
    MarketContext,
)
from app.modules.investment.domain.policy import (
    CashOpportunity,
    EquityOpportunity,
    FixedIncomeOpportunity,
    PredictionQuality,
)
from app.modules.investment.domain.risk_budget import (
    BALANCED_BUDGET,
    CONSERVATIVE_BUDGET,
    GROWTH_BUDGET,
    get_risk_budget,
)


def test_calibration_buckets_deterministic_no_leakage() -> None:
    pairs = [
        (0.01, 0.005),
        (0.03, 0.04),
        (0.07, 0.02),
        (0.12, 0.15),
        (-0.02, -0.01),
    ]
    cal = calibrate_equity_predictions(pairs, min_adequate=3, min_weak=2)
    assert cal.sample_size == 5
    assert cal.bias is not None
    assert cal.mae is not None
    names = [b.name for b in cal.buckets]
    assert names == ["lt_0", "0_2pct", "2_5pct", "5_10pct", "gt_10pct"]
    assert sum(b.n for b in cal.buckets) == 5
    # Realized matching: bucket 0_2pct has predicted 0.01
    b02 = next(b for b in cal.buckets if b.name == "0_2pct")
    assert b02.n == 1
    assert b02.mean_predicted == pytest.approx(0.01)
    assert b02.mean_realized == pytest.approx(0.005)


def test_calibration_insufficient_sample_unknown_confidence() -> None:
    cal = calibrate_equity_predictions([(0.02, 0.01)], min_weak=10)
    assert cal.calibration_status is CalibrationStatus.INSUFFICIENT_SAMPLE
    assert "UNKNOWN" in cal.uncertainty_note or "Мало" in cal.uncertainty_note


def test_empty_calibration() -> None:
    cal = calibrate_equity_predictions([])
    assert cal.sample_size == 0
    assert cal.calibration_status is CalibrationStatus.INSUFFICIENT_SAMPLE


def test_risk_budgets_deterministic() -> None:
    assert get_risk_budget(CONSERVATIVE_BUDGET.profile_id).max_equity_weight == 0.30
    assert get_risk_budget(BALANCED_BUDGET.profile_id).min_cash == 0.10
    assert get_risk_budget(GROWTH_BUDGET.profile_id).max_equity_weight == 0.90


def _market(**kwargs) -> MarketContext:
    base = dict(
        as_of_date=date(2026, 9, 5),
        available_capital=Decimal("100000"),
        cbr_hurdle_annual=0.18,
    )
    base.update(kwargs)
    return MarketContext(**base)  # type: ignore[arg-type]


def test_decision_weights_sum_and_non_negative() -> None:
    equity = EquityOpportunity(
        expected_return=0.25,
        expected_excess_return=0.07,
        confidence=None,
        model_source="test",
        timestamp=date(2026, 9, 5),
        prediction_quality=PredictionQuality.UNKNOWN,
        calibration_status="INSUFFICIENT_SAMPLE",
    )
    fi = FixedIncomeOpportunity(
        expected_yield=0.14,
        duration=4.0,
        credit_quality="UNKNOWN",
        liquidity="UNKNOWN",
        data_quality="READY",
        supported_ratio=0.4,
        support_status="SUPPORTED",
    )
    cash = CashOpportunity(0.18, 0.18, "CBR", "DATE_ONLY")
    decision = InvestmentDecisionEngine().decide(
        equity=equity,
        fixed_income=fi,
        cash=cash,
        risk_budget=BALANCED_BUDGET,
        market=_market(),
    )
    assert decision.equity_weight + decision.fixed_income_weight + decision.cash_weight == pytest.approx(
        1.0
    )
    assert decision.equity_weight >= 0
    assert decision.fixed_income_weight >= 0
    assert decision.cash_weight >= 0
    assert decision.explanations
    assert decision.why_equity_ru
    assert decision.reason_codes


def test_conservative_blocks_unknown_credit() -> None:
    equity = EquityOpportunity(
        None,
        -0.01,
        None,
        "test",
        date(2026, 9, 5),
        prediction_quality=PredictionQuality.UNKNOWN,
        calibration_status="UNKNOWN",
    )
    fi = FixedIncomeOpportunity(
        0.2,
        3.0,
        "UNKNOWN",
        "UNKNOWN",
        "READY",
        0.5,
        support_status="SUPPORTED",
    )
    decision = InvestmentDecisionEngine().decide(
        equity=equity,
        fixed_income=fi,
        cash=CashOpportunity(0.18, 0.18, "CBR", "DATE_ONLY"),
        risk_budget=CONSERVATIVE_BUDGET,
        market=_market(),
    )
    assert decision.fixed_income_weight == pytest.approx(0.0)
    assert decision.cash_weight >= CONSERVATIVE_BUDGET.min_cash - 1e-9
    assert "credit_risk_blocked_by_conservative_budget" in decision.reason_codes


def test_missing_equity_excess_no_fake_confidence() -> None:
    equity = EquityOpportunity(
        None,
        None,
        None,
        "test",
        date(2026, 9, 5),
        prediction_quality=PredictionQuality.UNKNOWN,
        calibration_status="UNKNOWN",
    )
    decision = InvestmentDecisionEngine().decide(
        equity=equity,
        fixed_income=None,
        cash=CashOpportunity(0.18, 0.18, "CBR", "DATE_ONLY"),
        risk_budget=GROWTH_BUDGET,
        market=_market(),
    )
    assert decision.equity_weight == pytest.approx(0.0)
    assert any("insufficient_data" in c for c in decision.reason_codes)
    assert "Недостаточно" in decision.why_equity_ru or "премии" in decision.why_equity_ru


def test_constraints_respected_min_cash() -> None:
    equity = EquityOpportunity(
        0.3,
        0.1,
        None,
        "test",
        date(2026, 9, 5),
        calibration_status="WEAK",
    )
    fi = FixedIncomeOpportunity(
        0.12,
        5.0,
        "OBSERVED",
        "OK",
        "READY",
        1.0,
        support_status="SUPPORTED",
    )
    decision = InvestmentDecisionEngine().decide(
        equity=equity,
        fixed_income=fi,
        cash=CashOpportunity(0.18, 0.18, "CBR", "DATE_ONLY"),
        risk_budget=CONSERVATIVE_BUDGET,
        market=_market(),
    )
    assert decision.cash_weight + 1e-9 >= CONSERVATIVE_BUDGET.min_cash
    assert decision.equity_weight <= CONSERVATIVE_BUDGET.max_equity_weight + 1e-9
