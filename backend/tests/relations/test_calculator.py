"""Unit tests for RelationCalculator — synthetic series and no look-ahead."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import numpy as np
import pytest

from app.modules.relations.application.calculator import InputSeries, RelationCalculator
from app.modules.relations.relation_config import BASIC_RELATIONS_V1


def _dates(n: int, start: date = date(2024, 1, 1)) -> tuple[date, ...]:
    return tuple(start + timedelta(days=i) for i in range(n))


def _series(values: list[float], start: date = date(2024, 1, 1)) -> InputSeries:
    return InputSeries(input_id=uuid4(), dates=_dates(len(values), start), values=tuple(values))


@pytest.fixture
def calc() -> RelationCalculator:
    return RelationCalculator(BASIC_RELATIONS_V1["parameters"])


def test_positive_correlation(calc: RelationCalculator) -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 80)
    y = x + rng.normal(0, 0.1, 80)
    a, b = _series(x.tolist()), _series(y.tolist())
    results = calc.calculate_as_of(
        {a.input_id: a, b.input_id: b},
        as_of_date=a.dates[-1],
        input_ids=[a.input_id, b.input_id],
    )
    zero60 = [r for r in results if r.window_observations == 60][0]
    assert zero60.pearson is not None and zero60.pearson > 0.9
    assert zero60.is_valid


def test_inverse_correlation(calc: RelationCalculator) -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(0, 1, 80)
    y = -x + rng.normal(0, 0.05, 80)
    a, b = _series(x.tolist()), _series(y.tolist())
    results = calc.calculate_as_of(
        {a.input_id: a, b.input_id: b},
        as_of_date=a.dates[-1],
        input_ids=[a.input_id, b.input_id],
    )
    zero60 = [r for r in results if r.window_observations == 60][0]
    assert zero60.pearson is not None and zero60.pearson < -0.9


def test_spearman_monotonic(calc: RelationCalculator) -> None:
    x = list(range(1, 61))
    y = [v**2 for v in x]
    a, b = _series([float(v) for v in x]), _series([float(v) for v in y])
    results = calc.calculate_as_of(
        {a.input_id: a, b.input_id: b},
        as_of_date=a.dates[-1],
        input_ids=[a.input_id, b.input_id],
    )
    zero60 = [r for r in results if r.window_observations == 60][0]
    assert zero60.spearman is not None and zero60.spearman > 0.99


def test_known_lag_2(calc: RelationCalculator) -> None:
    rng = np.random.default_rng(2)
    leader = rng.normal(0, 1, 100)
    follower = np.zeros(100)
    follower[2:] = leader[:-2]
    a = _series(leader.tolist())
    b = _series(follower.tolist())
    # Force a < b ordering by using known ids via rebuild
    results = calc.calculate_as_of(
        {a.input_id: a, b.input_id: b},
        as_of_date=a.dates[-1],
        input_ids=[a.input_id, b.input_id],
    )
    zero60 = [r for r in results if r.window_observations == 60][0]
    assert zero60.best_lag == 2
    assert zero60.best_leader_input_id == a.input_id
    assert zero60.best_follower_input_id == b.input_id
    # Full lag profile: both directions × lags 1..5
    assert len(zero60.lag_metrics) == 10
    lag2 = [
        m
        for m in zero60.lag_metrics
        if m.lag == 2 and m.leader_input_id == a.input_id and m.follower_input_id == b.input_id
    ][0]
    assert lag2.pearson is not None and lag2.pearson > 0.9


def test_no_lookahead_future_does_not_affect(calc: RelationCalculator) -> None:
    base_vals = [float(i % 7 - 3) for i in range(40)]
    a = _series(base_vals + [0.0] * 20)
    b_clean = _series([v * 0.9 for v in base_vals] + [0.0] * 20)
    b_poison = _series([v * 0.9 for v in base_vals] + [999.0] * 20)
    as_of = a.dates[39]
    r1 = calc.calculate_as_of(
        {a.input_id: a, b_clean.input_id: b_clean},
        as_of_date=as_of,
        input_ids=[a.input_id, b_clean.input_id],
    )
    # Rebind poison series to same ids
    a2 = InputSeries(input_id=a.input_id, dates=a.dates, values=a.values)
    b2 = InputSeries(input_id=b_clean.input_id, dates=b_poison.dates, values=b_poison.values)
    r2 = calc.calculate_as_of(
        {a2.input_id: a2, b2.input_id: b2},
        as_of_date=as_of,
        input_ids=[a2.input_id, b2.input_id],
    )
    w20_1 = [r for r in r1 if r.window_observations == 20][0]
    w20_2 = [r for r in r2 if r.window_observations == 20][0]
    assert w20_1.pearson == pytest.approx(w20_2.pearson)
    assert w20_1.sample_count == w20_2.sample_count
    # Lag metrics also unchanged
    assert [m.pearson for m in w20_1.lag_metrics] == [m.pearson for m in w20_2.lag_metrics]


def test_unordered_pair_and_no_self(calc: RelationCalculator) -> None:
    a = _series([1.0, 2.0, 3.0] * 20)
    b = _series([2.0, 3.0, 4.0] * 20)
    results = calc.calculate_as_of(
        {a.input_id: a, b.input_id: b},
        as_of_date=a.dates[-1],
        input_ids=[a.input_id, b.input_id],
    )
    assert all(r.input_a_id < r.input_b_id for r in results)
    assert len({(r.input_a_id, r.input_b_id, r.window_observations) for r in results}) == len(results)


def test_min_coverage_invalid(calc: RelationCalculator) -> None:
    a = _series([1.0] * 10)
    b = _series([1.0] * 5)  # short series → low coverage for window 20
    results = calc.calculate_as_of(
        {a.input_id: a, b.input_id: b},
        as_of_date=a.dates[-1],
        input_ids=[a.input_id, b.input_id],
    )
    w20 = [r for r in results if r.window_observations == 20][0]
    assert w20.is_valid is False
    assert w20.quality_flags.get("insufficient_samples") is True


def test_stability_null_for_window_20(calc: RelationCalculator) -> None:
    rng = np.random.default_rng(3)
    a = _series(rng.normal(0, 1, 80).tolist())
    b = _series((np.asarray(a.values) * 0.8 + rng.normal(0, 0.2, 80)).tolist())
    results = calc.calculate_as_of(
        {a.input_id: a, b.input_id: b},
        as_of_date=a.dates[-1],
        input_ids=[a.input_id, b.input_id],
    )
    w20 = [r for r in results if r.window_observations == 20][0]
    w60 = [r for r in results if r.window_observations == 60][0]
    assert w20.rolling_corr_mean is None
    assert w20.sign_consistency is None
    assert w60.rolling_corr_mean is not None


def test_window_observations_field(calc: RelationCalculator) -> None:
    a = _series([float(i) for i in range(130)])
    b = _series([float(i) * 1.1 for i in range(130)])
    results = calc.calculate_as_of(
        {a.input_id: a, b.input_id: b},
        as_of_date=a.dates[-1],
        input_ids=[a.input_id, b.input_id],
    )
    windows = {r.window_observations for r in results}
    assert windows == {20, 60, 120}


def test_tie_break_smaller_lag(calc: RelationCalculator) -> None:
    # Construct equal |corr| at lag 1 and 2 — prefer smaller lag
    # Simple: constant lag-1 relation with noise making lag2 similar is hard;
    # verify selection prefers smaller lag when abs equal by using identical lag scores.
    leader = [1.0, -1.0] * 40
    follower = [0.0] + leader[:-1]  # perfect lag 1
    a = _series(leader)
    b = _series(follower)
    results = calc.calculate_as_of(
        {a.input_id: a, b.input_id: b},
        as_of_date=a.dates[-1],
        input_ids=[a.input_id, b.input_id],
    )
    zero60 = [r for r in results if r.window_observations == 60][0]
    assert zero60.best_lag == 1
