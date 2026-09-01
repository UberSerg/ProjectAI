"""Relation as-of join unit tests."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.modules.learning.application.relations_join import RelationIndex, extract_relation_features, ordered_pair


def test_ordered_pair_stable() -> None:
    a, b = uuid4(), uuid4()
    lo, hi = ordered_pair(a, b)
    assert lo < hi
    assert ordered_pair(b, a) == (lo, hi)


def test_relation_as_of_selection() -> None:
    ia, ib = ordered_pair(uuid4(), uuid4())
    s1 = SimpleNamespace(
        id=1,
        input_a_id=ia,
        input_b_id=ib,
        window_observations=60,
        as_of_date=date(2024, 1, 1),
        pearson=0.1,
        spearman=0.1,
        rolling_corr_std=0.2,
        sign_consistency=0.5,
    )
    s2 = SimpleNamespace(
        id=2,
        input_a_id=ia,
        input_b_id=ib,
        window_observations=60,
        as_of_date=date(2024, 1, 8),
        pearson=0.9,
        spearman=0.8,
        rolling_corr_std=0.1,
        sign_consistency=0.9,
    )
    index = RelationIndex.build([s1, s2], {1: [], 2: []})  # type: ignore[arg-type]
    snap, _, age = index.as_of(ia, ib, 60, date(2024, 1, 3), max_age_days=8)
    assert snap is not None and snap.id == 1
    assert age == 2
    snap2, _, _ = index.as_of(ia, ib, 60, date(2024, 1, 8), max_age_days=8)
    assert snap2 is not None and snap2.id == 2
    snap3, _, age3 = index.as_of(ia, ib, 60, date(2024, 1, 20), max_age_days=8)
    assert snap3 is None
    assert age3 == 12  # stale


def test_self_relation_null() -> None:
    uid = uuid4()
    index = RelationIndex.build([], {})
    feats, meta = extract_relation_features(
        context_key="imoex",
        subject_input_id=uid,
        context_input_id=uid,
        windows=[20, 60, 120],
        lag_window=60,
        lags=[1, 2, 3, 4, 5],
        index=index,
        as_of=date(2024, 1, 1),
        max_age_days=8,
    )
    assert meta["reason"] == "self_relation"
    assert all(v is None for v in feats.values())
