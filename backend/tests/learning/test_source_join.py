"""PIT source selection, version pins, no-look-ahead, future mutation for X(t)."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from app.modules.learning.application.hash_util import sample_content_hash
from app.modules.learning.application.labels import ForwardReturnLabelCalculator, PriceObservation
from app.modules.learning.application.source_join import (
    ANALYTICS_FEATURE_KEYS,
    TECHNICAL_RAW_FEATURE_KEYS,
    TECHNICAL_SIGNAL_ATTRS,
    merge_phase1_features,
    select_exact_as_of,
    select_pinned_model,
    select_pinned_version,
)
from app.modules.learning.dataset_config import (
    FEATURE_MANIFEST_V1,
    RELATIONS_JOIN_ENABLED,
    feature_names_from_manifest,
)


def _basic(*, return_5d: float, row_id: int = 1, is_valid: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id,
        date=date(2024, 6, 1),
        is_valid=is_valid,
        quality_flags={},
        return_1d=0.01,
        return_5d=return_5d,
        return_20d=0.03,
        volatility_5d=0.02,
        volatility_20d=0.04,
        drawdown_20d=-0.05,
        volume_change_1d=0.1,
        volume_zscore_20d=1.2,
    )


def _tech(*, rsi14: float, row_id: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id,
        date=date(2024, 6, 1),
        is_valid=True,
        quality_flags={},
        sma20_distance=0.01,
        ema20_distance=0.02,
        rsi14=rsi14,
        atr14_pct=0.015,
    )


def _signal(*, score: float, row_id: int = 20, model_version: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id,
        as_of_date=date(2024, 6, 1),
        is_valid=True,
        quality_flags={},
        model_code="rules",
        model_version=model_version,
        score=score,
        confidence=0.7,
        direction="bullish",
        trend_contribution=0.1,
        momentum_contribution=0.2,
        rsi_contribution=0.05,
        volume_contribution=0.0,
    )


def test_relations_join_enabled_in_config() -> None:
    assert RELATIONS_JOIN_ENABLED is True


def test_builder_imports_relations_join() -> None:
    import app.modules.learning.application.builder as builder_mod

    assert "extract_all_relation_features" in builder_mod.__dict__
    assert "RelationIndex" in builder_mod.__dict__


def test_select_exact_as_of_never_looks_ahead() -> None:
    as_of = date(2024, 6, 1)
    future = date(2024, 6, 3)
    rows = {
        as_of: _basic(return_5d=0.02, row_id=1),
        future: _basic(return_5d=0.99, row_id=2),
    }
    chosen = select_exact_as_of(rows, as_of)
    assert chosen is not None
    assert chosen.id == 1
    assert chosen.return_5d == 0.02
    assert select_exact_as_of(rows, date(2024, 5, 31)) is None


def test_no_look_ahead_future_row_mutation_does_not_change_x() -> None:
    as_of = date(2024, 6, 1)
    future = date(2024, 6, 10)
    basic_a = {as_of: _basic(return_5d=0.02), future: _basic(return_5d=0.10, row_id=99)}
    basic_b = {as_of: _basic(return_5d=0.02), future: _basic(return_5d=-0.90, row_id=99)}
    tech = {as_of: _tech(rsi14=55.0), future: _tech(rsi14=99.0, row_id=98)}
    sig = {as_of: _signal(score=0.3), future: _signal(score=-0.9, row_id=97)}

    xa, _ = merge_phase1_features(
        select_exact_as_of(basic_a, as_of),
        select_exact_as_of(tech, as_of),
        select_exact_as_of(sig, as_of),
    )
    xb, _ = merge_phase1_features(
        select_exact_as_of(basic_b, as_of),
        select_exact_as_of(tech, as_of),
        select_exact_as_of(sig, as_of),
    )
    assert xa == xb
    assert xa["return_5d"] == 0.02
    assert xa["rsi14"] == 55.0
    assert xa["technical_score"] == 0.3
    assert "forward_return_5d" not in xa


def test_version_pin_ignores_active_v2_rows() -> None:
    as_of = date(2024, 6, 1)
    by_version = {
        1: {as_of: _basic(return_5d=0.02, row_id=1)},
        2: {as_of: _basic(return_5d=0.88, row_id=2)},
    }
    pinned = select_pinned_version(by_version, pinned_version=1, as_of=as_of)
    assert pinned is not None
    assert pinned.id == 1
    assert pinned.return_5d == 0.02
    active_v2 = select_pinned_version(by_version, pinned_version=2, as_of=as_of)
    assert active_v2 is not None
    assert active_v2.return_5d == 0.88


def test_technical_model_pin_ignores_other_model_version() -> None:
    as_of = date(2024, 6, 1)
    by_model = {
        ("rules", 1): {as_of: _signal(score=0.25, row_id=1, model_version=1)},
        ("rules", 2): {as_of: _signal(score=0.91, row_id=2, model_version=2)},
    }
    pinned = select_pinned_model(by_model, "rules", 1, as_of)
    assert pinned is not None
    assert pinned.id == 1
    assert pinned.score == 0.25


def test_phase1_feature_vector_has_no_labels() -> None:
    values, direction = merge_phase1_features(_basic(return_5d=0.02), _tech(rsi14=40.0), _signal(score=-0.1))
    assert direction == "bearish" or direction == "bullish"
    assert set(ANALYTICS_FEATURE_KEYS).issubset(values)
    assert set(TECHNICAL_RAW_FEATURE_KEYS).issubset(values)
    assert set(TECHNICAL_SIGNAL_ATTRS).issubset(values)
    assert not any(name.startswith("forward_return_") for name in values)
    manifest_features = set(feature_names_from_manifest(FEATURE_MANIFEST_V1))
    assert set(values) <= manifest_features


def test_future_mutation_x_stable_y_changes() -> None:
    start = date(2024, 1, 2)
    as_of = start + timedelta(days=10)
    base_closes = [100.0 + i * 0.5 for i in range(30)]
    prices_a = [
        PriceObservation(date=start + timedelta(days=i), close=c, candle_id=i + 1)
        for i, c in enumerate(base_closes + [200.0, 210.0])
    ]
    prices_b = [
        PriceObservation(date=start + timedelta(days=i), close=c, candle_id=i + 1)
        for i, c in enumerate(base_closes[:15] + [50.0] + base_closes[16:])
    ]
    basic = {as_of: _basic(return_5d=0.02)}
    tech = {as_of: _tech(rsi14=55.0)}
    sig = {as_of: _signal(score=0.3)}
    xa, _ = merge_phase1_features(
        select_exact_as_of(basic, as_of),
        select_exact_as_of(tech, as_of),
        select_exact_as_of(sig, as_of),
    )
    xb, _ = merge_phase1_features(
        select_exact_as_of(basic, as_of),
        select_exact_as_of(tech, as_of),
        select_exact_as_of(sig, as_of),
    )
    assert xa == xb
    calc = ForwardReturnLabelCalculator([5])
    ya = calc.calculate(prices_a, as_of=as_of)
    yb = calc.calculate(prices_b, as_of=as_of)
    assert ya.labels.forward_return_5d != yb.labels.forward_return_5d
    hash_a = sample_content_hash(
        instrument_id=1,
        as_of_date=as_of.isoformat(),
        features=xa,
        labels=ya.labels.to_dict(),
        lineage_identity={"basic_feature_id": 1},
    )
    hash_b = sample_content_hash(
        instrument_id=1,
        as_of_date=as_of.isoformat(),
        features=xb,
        labels=yb.labels.to_dict(),
        lineage_identity={"basic_feature_id": 1},
    )
    assert hash_a != hash_b
