"""Unit tests for RuleBasedTechnicalModel — pure, no DB."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.domain.ports.technical import (
    FeatureSetRef,
    SignalDirection,
    TechnicalFeatureVector,
    TechnicalModelInput,
    TechnicalQualityContext,
)
from app.infrastructure.ml.technical_rules import RuleBasedTechnicalModel
from app.modules.technical.technical_config import RULES_V1_CONFIG


def _input(
    *,
    features: TechnicalFeatureVector | None = None,
    quality: TechnicalQualityContext | None = None,
) -> TechnicalModelInput:
    return TechnicalModelInput(
        instrument_id=1,
        ticker="TEST",
        as_of_date=date(2024, 6, 1),
        basic_feature_set_ref=FeatureSetRef(code="basic_daily", version=1, id=uuid4()),
        technical_feature_set_ref=FeatureSetRef(code="technical_daily", version=1, id=uuid4()),
        features=features
        or TechnicalFeatureVector(
            return_5d=0.12,
            return_20d=0.15,
            sma20_distance=0.06,
            ema20_distance=0.05,
            rsi14=70.0,
            volume_zscore_20d=3.0,
            atr14_pct=0.02,
        ),
        quality=quality or TechnicalQualityContext(),
    )


def test_strong_positive_bullish() -> None:
    model = RuleBasedTechnicalModel(RULES_V1_CONFIG)
    out = model.predict(_input())
    assert out.score >= 0.20
    assert out.direction is SignalDirection.BULLISH
    assert out.factor_contributions.trend is not None
    assert out.factor_contributions.momentum is not None


def test_strong_negative_bearish() -> None:
    model = RuleBasedTechnicalModel(RULES_V1_CONFIG)
    out = model.predict(
        _input(
            features=TechnicalFeatureVector(
                return_5d=-0.12,
                return_20d=-0.15,
                sma20_distance=-0.06,
                ema20_distance=-0.05,
                rsi14=30.0,
                volume_zscore_20d=3.0,
            )
        )
    )
    assert out.score <= -0.20
    assert out.direction is SignalDirection.BEARISH


def test_mixed_neutral() -> None:
    model = RuleBasedTechnicalModel(RULES_V1_CONFIG)
    out = model.predict(
        _input(
            features=TechnicalFeatureVector(
                return_5d=0.01,
                return_20d=-0.01,
                sma20_distance=0.005,
                ema20_distance=-0.005,
                rsi14=50.0,
                volume_zscore_20d=0.0,
            )
        )
    )
    assert out.direction is SignalDirection.NEUTRAL
    assert abs(out.score) < 0.20


def test_missing_factor_lowers_confidence() -> None:
    model = RuleBasedTechnicalModel(RULES_V1_CONFIG)
    full = model.predict(_input())
    missing = model.predict(
        _input(
            features=TechnicalFeatureVector(
                return_5d=0.12,
                return_20d=0.15,
                # no sma/ema → trend missing
                rsi14=70.0,
                volume_zscore_20d=3.0,
            )
        )
    )
    assert missing.confidence < full.confidence


def test_critical_quality_invalidates() -> None:
    model = RuleBasedTechnicalModel(RULES_V1_CONFIG)
    out = model.predict(
        _input(
            quality=TechnicalQualityContext(
                is_valid=False,
                critical=True,
                quality_flags={"price_discontinuity": True},
            )
        )
    )
    assert out.is_valid is False
    assert out.confidence == 0.0
    assert out.direction is SignalDirection.NEUTRAL


def test_score_clamped() -> None:
    model = RuleBasedTechnicalModel(RULES_V1_CONFIG)
    out = model.predict(
        _input(
            features=TechnicalFeatureVector(
                return_5d=5.0,
                return_20d=5.0,
                sma20_distance=5.0,
                ema20_distance=5.0,
                rsi14=100.0,
                volume_zscore_20d=10.0,
            )
        )
    )
    assert out.score <= 1.0
    assert out.score >= -1.0


def test_model_purity_no_db_imports_in_predict() -> None:
    # Smoke: predict runs without session/engine.
    model = RuleBasedTechnicalModel()
    out = model.predict(_input())
    assert out.model_code == "rules"
    assert "config_hash" in out.metadata
