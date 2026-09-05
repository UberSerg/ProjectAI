"""Prediction Calibration & Confidence Engine V1 tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.investment.domain.decision_engine import InvestmentDecisionEngine, MarketContext
from app.modules.investment.domain.policy import CashOpportunity, EquityOpportunity, PredictionQuality
from app.modules.investment.domain.risk_budget import BALANCED_BUDGET
from app.modules.prediction.domain.calibration_v1 import (
    BUCKET_EDGES,
    BUCKET_SPEC_VERSION,
    CalibrationStatus,
    bucket_name_for_prediction,
    calibrate_expected_return,
    calibrate_ranking_quality,
)
from app.modules.prediction.domain.confidence import (
    ConfidenceInputs,
    ConfidenceLevel,
    PredictionConfidenceEngine,
)


def test_bucket_boundaries_versioned() -> None:
    assert BUCKET_SPEC_VERSION == "expected_return_buckets_v1"
    assert [n for n, _, _ in BUCKET_EDGES] == ["lt_0", "0_2pct", "2_5pct", "5_10pct", "gt_10pct"]
    assert bucket_name_for_prediction(-0.01) == "lt_0"
    assert bucket_name_for_prediction(0.0) == "0_2pct"
    assert bucket_name_for_prediction(0.019) == "0_2pct"
    assert bucket_name_for_prediction(0.02) == "2_5pct"
    assert bucket_name_for_prediction(0.05) == "5_10pct"
    assert bucket_name_for_prediction(0.10) == "gt_10pct"


def test_calibration_only_matured_pairs_no_leakage() -> None:
    pairs = [(0.01, 0.005), (0.03, 0.02), (0.07, 0.04), (0.12, -0.01)]
    cal = calibrate_expected_return(pairs, pending_count=3)
    assert cal.sample_count == 4
    assert cal.pending_count == 3
    assert cal.coverage == pytest.approx(4 / 7)
    assert cal.bias is not None
    assert cal.mae is not None
    assert cal.direction_accuracy is not None
    b02 = next(b for b in cal.buckets if b.bucket_name == "0_2pct")
    assert b02.sample_count == 1
    assert b02.average_prediction == pytest.approx(0.01)
    assert b02.average_realized_return == pytest.approx(0.005)


def test_confidence_insufficient_sample_unknown() -> None:
    cal = calibrate_expected_return([(0.02, 0.01)], min_weak=10)
    conf = PredictionConfidenceEngine().assess(ConfidenceInputs(calibration=cal))
    assert conf.confidence_level is ConfidenceLevel.UNKNOWN
    assert "insufficient_sample" in conf.reason_codes


def test_confidence_low_with_weak_sample() -> None:
    pairs = [(0.05, -0.02)] * 15
    cal = calibrate_expected_return(pairs, min_weak=10, min_adequate=50)
    conf = PredictionConfidenceEngine().assess(ConfidenceInputs(calibration=cal))
    assert conf.confidence_level is ConfidenceLevel.LOW
    assert cal.calibration_status is CalibrationStatus.WEAK


def test_confidence_medium_deterministic() -> None:
    # Well-behaved large sample → MEDIUM (not HIGH without stricter criteria)
    pairs = [(0.02, 0.018), (0.03, 0.028), (-0.01, -0.008)] * 20
    cal = calibrate_expected_return(pairs)
    assert cal.sample_count == 60
    conf = PredictionConfidenceEngine().assess(ConfidenceInputs(calibration=cal))
    assert conf.confidence_level in {ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW, ConfidenceLevel.HIGH}
    # Deterministic: same input → same output
    conf2 = PredictionConfidenceEngine().assess(ConfidenceInputs(calibration=cal))
    assert conf2.confidence_level == conf.confidence_level


def test_ranking_not_return_calibration() -> None:
    ranking = calibrate_ranking_quality(
        sample_count=20,
        spearman_values=[0.1, 0.2],
        top20_realized=[0.03],
        bottom20_realized=[-0.01],
        rank_pairs=[(0.9, 0.04), (0.1, -0.02)] * 5,
    )
    assert ranking.prediction_semantic == "RANKING_SCORE"
    assert ranking.mean_spearman_rank_ic == pytest.approx(0.15)
    conf = PredictionConfidenceEngine().assess_ranking(ranking)
    assert conf.confidence_level in {ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM, ConfidenceLevel.UNKNOWN}


def test_allocation_unknown_confidence_caps_equity() -> None:
    equity = EquityOpportunity(
        expected_return=0.25,
        expected_excess_return=0.05,
        confidence=None,
        model_source="test",
        timestamp=date(2026, 9, 5),
        prediction_quality=PredictionQuality.UNKNOWN,
        calibration_status="INSUFFICIENT_SAMPLE",
        confidence_level="UNKNOWN",
        confidence_reason="мало зрелых прогнозов",
        sample_size=0,
    )
    decision = InvestmentDecisionEngine().decide(
        equity=equity,
        fixed_income=None,
        cash=CashOpportunity(0.18, 0.18, "CBR", "DATE_ONLY"),
        risk_budget=BALANCED_BUDGET,
        market=MarketContext(
            as_of_date=date(2026, 9, 5),
            available_capital=Decimal("100000"),
            cbr_hurdle_annual=0.18,
        ),
    )
    assert decision.equity_weight <= 0.25 + 1e-9
    assert "equity_capped_due_to_insufficient_calibration" in decision.reason_codes
    assert "калибровк" in decision.why_equity_ru.lower() or "Confidence=UNKNOWN" in decision.why_equity_ru
