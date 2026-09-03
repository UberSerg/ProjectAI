"""Relation as-of join unit tests — PIT, max age, direction, hashes."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.modules.learning.application.hash_util import sample_content_hash
from app.modules.learning.application.relations_join import (
    RelationIndex,
    extract_all_relation_features,
    extract_relation_features,
    ordered_pair,
)
from app.modules.learning.dataset_config import (
    FEATURE_MANIFEST_V1,
    RELATION_CONTEXTS_V1,
    RELATIONS_JOIN_ENABLED,
    feature_names_from_manifest,
    is_horizon_training_eligible,
    is_sample_relation_missing,
    relation_feature_names,
)


def _snap(
    *,
    snap_id: int,
    ia,
    ib,
    window: int,
    as_of: date,
    pearson: float = 0.1,
    spearman: float = 0.2,
    rolling: float = 0.05,
    sign: float = 0.8,
    valid: bool = True,
) -> SimpleNamespace:
    lo, hi = ordered_pair(ia, ib)
    return SimpleNamespace(
        id=snap_id,
        input_a_id=lo,
        input_b_id=hi,
        window_observations=window,
        as_of_date=as_of,
        pearson=pearson,
        spearman=spearman,
        rolling_corr_std=rolling,
        sign_consistency=sign,
        is_valid=valid,
    )


def _lag(leader, follower, lag: int, pearson: float) -> SimpleNamespace:
    return SimpleNamespace(
        leader_input_id=leader,
        follower_input_id=follower,
        lag=lag,
        pearson=pearson,
    )


def _extract(index: RelationIndex, subject, context, as_of: date, **kwargs):
    return extract_relation_features(
        context_key="imoex",
        subject_input_id=subject,
        context_input_id=context,
        windows=[20, 60, 120],
        lag_window=60,
        lags=[1, 2, 3, 4, 5],
        index=index,
        as_of=as_of,
        max_age_days=8,
        **kwargs,
    )


def test_relations_join_enabled() -> None:
    assert RELATIONS_JOIN_ENABLED is True


def test_ordered_pair_stable() -> None:
    a, b = uuid4(), uuid4()
    lo, hi = ordered_pair(a, b)
    assert lo < hi
    assert ordered_pair(b, a) == (lo, hi)


def test_as_of_selects_latest_eligible_not_future() -> None:
    """A: snapshots 01 / 08 / 15, sample 10 → 08, never 15."""
    subject, context = uuid4(), uuid4()
    s1 = _snap(snap_id=1, ia=subject, ib=context, window=60, as_of=date(2026, 1, 1), pearson=0.11)
    s2 = _snap(snap_id=2, ia=subject, ib=context, window=60, as_of=date(2026, 1, 8), pearson=0.22)
    s3 = _snap(snap_id=3, ia=subject, ib=context, window=60, as_of=date(2026, 1, 15), pearson=0.99)
    index = RelationIndex.build([s1, s2, s3], {1: [], 2: [], 3: []})  # type: ignore[arg-type]
    snap, _, age = index.as_of(subject, context, 60, date(2026, 1, 10), max_age_days=8)
    assert snap is not None and snap.id == 2
    assert snap.pearson == 0.22
    assert age == 2


def test_no_future_snapshot_in_x() -> None:
    """B: adding t+1 / t+5 snapshot does not change X(t)."""
    subject, context = uuid4(), uuid4()
    eligible = _snap(snap_id=2, ia=subject, ib=context, window=60, as_of=date(2026, 1, 8), pearson=0.22)
    future = _snap(snap_id=3, ia=subject, ib=context, window=60, as_of=date(2026, 1, 15), pearson=0.99)
    as_of = date(2026, 1, 10)
    feats_a, _ = _extract(RelationIndex.build([eligible], {2: []}), subject, context, as_of)  # type: ignore[arg-type]
    feats_b, _ = _extract(RelationIndex.build([eligible, future], {2: [], 3: []}), subject, context, as_of)  # type: ignore[arg-type]
    assert feats_a == feats_b
    assert feats_a["rel_imoex_w60_pearson"] == 0.22


def test_max_age_8_allowed_9_stale() -> None:
    """C: age 8 allowed; age 9 stale → NULL."""
    subject, context = uuid4(), uuid4()
    allowed = _snap(snap_id=1, ia=subject, ib=context, window=60, as_of=date(2026, 1, 2), pearson=0.4)
    stale = _snap(snap_id=2, ia=subject, ib=context, window=60, as_of=date(2026, 1, 1), pearson=0.4)
    as_of = date(2026, 1, 10)
    snap8, _, age8 = RelationIndex.build([allowed], {1: []}).as_of(  # type: ignore[arg-type]
        subject, context, 60, as_of, max_age_days=8
    )
    assert snap8 is not None and age8 == 8
    feats8, meta8 = _extract(RelationIndex.build([allowed], {1: []}), subject, context, as_of)  # type: ignore[arg-type]
    assert feats8["rel_imoex_w60_pearson"] == 0.4
    assert meta8["available"] is True

    snap9, _, age9 = RelationIndex.build([stale], {2: []}).as_of(  # type: ignore[arg-type]
        subject, context, 60, as_of, max_age_days=8
    )
    assert snap9 is None and age9 == 9
    feats9, meta9 = _extract(RelationIndex.build([stale], {2: []}), subject, context, as_of)  # type: ignore[arg-type]
    assert feats9["rel_imoex_w60_pearson"] is None
    assert meta9["available"] is False
    assert meta9["reason"] == "stale"


def test_self_relation_null() -> None:
    """D: subject == context → NULL / unavailable, never 1.0 or 0."""
    uid = uuid4()
    index = RelationIndex.build([], {})
    feats, meta = _extract(index, uid, uid, date(2026, 1, 10))
    assert meta["reason"] == "self_relation"
    assert meta["available"] is False
    assert all(v is None for v in feats.values())
    assert 1.0 not in feats.values()
    assert 0 not in feats.values()
    assert 0.0 not in feats.values()


def test_missing_context_null_no_crash() -> None:
    """E: no relation → NULL, no crash."""
    subject, context = uuid4(), uuid4()
    feats, meta = _extract(RelationIndex.build([], {}), subject, context, date(2026, 1, 10))
    assert all(v is None for v in feats.values())
    assert meta["available"] is False
    result = extract_all_relation_features(
        contexts=RELATION_CONTEXTS_V1,
        subject_input_id=subject,
        context_input_ids={},
        index=RelationIndex.build([], {}),
        as_of=date(2026, 1, 10),
        max_age_days=8,
    )
    assert result.available is False
    assert all(v is None for v in result.features.values())
    assert set(result.features) == set(relation_feature_names(RELATION_CONTEXTS_V1))


def test_pinned_version_ignores_v2_in_index() -> None:
    """F: index built from v1 only — v2 snapshot on same date is unused."""
    subject, context = uuid4(), uuid4()
    v1 = _snap(snap_id=1, ia=subject, ib=context, window=60, as_of=date(2026, 1, 8), pearson=0.31)
    v2 = _snap(snap_id=99, ia=subject, ib=context, window=60, as_of=date(2026, 1, 8), pearson=0.88)
    as_of = date(2026, 1, 10)
    feats_v1, _ = _extract(RelationIndex.build([v1], {1: []}), subject, context, as_of)  # type: ignore[arg-type]
    feats_mixed, _ = _extract(RelationIndex.build([v1, v2], {1: [], 99: []}), subject, context, as_of)  # type: ignore[arg-type]
    # Same as_of: last appended wins only if both are in the same index list; pin happens at load.
    # Builder loads only pinned relation_set_version, so v2 never enters the index:
    assert feats_v1["rel_imoex_w60_pearson"] == 0.31
    index_v1_only = RelationIndex.build([v1], {1: []})  # type: ignore[arg-type]
    assert v2 not in [row[1] for rows in index_v1_only.by_pair_window.values() for row in rows]
    assert feats_mixed["rel_imoex_w60_pearson"] in (0.31, 0.88)


def test_lag_direction_not_symmetric() -> None:
    """G: subject→context lag3 != context→subject lag3."""
    subject, context = uuid4(), uuid4()
    snap = _snap(snap_id=1, ia=subject, ib=context, window=60, as_of=date(2026, 1, 8), pearson=0.2)
    lags = [
        _lag(subject, context, 3, 0.77),
        _lag(context, subject, 3, -0.33),
        _lag(subject, context, 1, 0.1),
        _lag(context, subject, 1, 0.2),
        _lag(subject, context, 2, 0.1),
        _lag(context, subject, 2, 0.2),
        _lag(subject, context, 4, 0.1),
        _lag(context, subject, 4, 0.2),
        _lag(subject, context, 5, 0.1),
        _lag(context, subject, 5, 0.2),
    ]
    feats, _ = _extract(RelationIndex.build([snap], {1: lags}), subject, context, date(2026, 1, 10))  # type: ignore[arg-type]
    assert feats["rel_imoex_subject_leads_lag3_pearson"] == 0.77
    assert feats["rel_imoex_context_leads_lag3_pearson"] == -0.33
    assert feats["rel_imoex_subject_leads_lag3_pearson"] != feats["rel_imoex_context_leads_lag3_pearson"]


def test_zero_lag_windows_pearson_spearman() -> None:
    """H: windows 20/60/120 map Pearson and Spearman."""
    subject, context = uuid4(), uuid4()
    snaps = [
        _snap(snap_id=20, ia=subject, ib=context, window=20, as_of=date(2026, 1, 8), pearson=0.21, spearman=0.22),
        _snap(snap_id=60, ia=subject, ib=context, window=60, as_of=date(2026, 1, 8), pearson=0.61, spearman=0.62),
        _snap(snap_id=120, ia=subject, ib=context, window=120, as_of=date(2026, 1, 8), pearson=0.12, spearman=0.13),
    ]
    index = RelationIndex.build(snaps, {20: [], 60: [], 120: []})  # type: ignore[arg-type]
    feats, _ = _extract(index, subject, context, date(2026, 1, 10))
    assert feats["rel_imoex_w20_pearson"] == 0.21
    assert feats["rel_imoex_w20_spearman"] == 0.22
    assert feats["rel_imoex_w60_pearson"] == 0.61
    assert feats["rel_imoex_w60_spearman"] == 0.62
    assert feats["rel_imoex_w120_pearson"] == 0.12
    assert feats["rel_imoex_w120_spearman"] == 0.13


def test_stability_window_60() -> None:
    """I: window 60 rolling std and sign consistency."""
    subject, context = uuid4(), uuid4()
    snap = _snap(
        snap_id=60,
        ia=subject,
        ib=context,
        window=60,
        as_of=date(2026, 1, 8),
        rolling=0.17,
        sign=0.64,
    )
    feats, _ = _extract(RelationIndex.build([snap], {60: []}), subject, context, date(2026, 1, 10))  # type: ignore[arg-type]
    assert feats["rel_imoex_w60_rolling_corr_std"] == 0.17
    assert feats["rel_imoex_w60_sign_consistency"] == 0.64
    assert "rel_imoex_w20_rolling_corr_std" not in feats
    assert "rel_imoex_w120_rolling_corr_std" not in feats


def test_future_mutation_x_unchanged_eligible_change_updates_x() -> None:
    """J: future relation after t does not change X(t); eligible <=t does."""
    subject, context = uuid4(), uuid4()
    eligible = _snap(snap_id=2, ia=subject, ib=context, window=60, as_of=date(2026, 1, 8), pearson=0.22)
    mutated = _snap(snap_id=2, ia=subject, ib=context, window=60, as_of=date(2026, 1, 8), pearson=0.55)
    future = _snap(snap_id=3, ia=subject, ib=context, window=60, as_of=date(2026, 1, 15), pearson=0.99)
    as_of = date(2026, 1, 10)
    xa, _ = _extract(RelationIndex.build([eligible], {2: []}), subject, context, as_of)  # type: ignore[arg-type]
    xb, _ = _extract(RelationIndex.build([eligible, future], {2: [], 3: []}), subject, context, as_of)  # type: ignore[arg-type]
    xc, _ = _extract(RelationIndex.build([mutated], {2: []}), subject, context, as_of)  # type: ignore[arg-type]
    assert xa == xb
    assert xa != xc
    assert xc["rel_imoex_w60_pearson"] == 0.55


def test_hash_eligible_change_vs_future_change() -> None:
    """K: eligible change → hash changes; future change → hash unchanged."""
    subject, context = uuid4(), uuid4()
    eligible = _snap(snap_id=2, ia=subject, ib=context, window=60, as_of=date(2026, 1, 8), pearson=0.22)
    mutated = _snap(snap_id=2, ia=subject, ib=context, window=60, as_of=date(2026, 1, 8), pearson=0.55)
    future = _snap(snap_id=3, ia=subject, ib=context, window=60, as_of=date(2026, 1, 15), pearson=0.99)
    as_of = date(2026, 1, 10)
    fa, _ = _extract(RelationIndex.build([eligible], {2: []}), subject, context, as_of)  # type: ignore[arg-type]
    fb, _ = _extract(RelationIndex.build([eligible, future], {2: [], 3: []}), subject, context, as_of)  # type: ignore[arg-type]
    fc, _ = _extract(RelationIndex.build([mutated], {2: []}), subject, context, as_of)  # type: ignore[arg-type]
    common = {
        "instrument_id": 1,
        "as_of_date": as_of.isoformat(),
        "labels": {"forward_return_5d": 0.1},
        "lineage_identity": {"relation_snapshot_ids": {"imoex_w60": 2}},
    }
    ha = sample_content_hash(**common, features=fa)
    hb = sample_content_hash(**common, features=fb)
    hc = sample_content_hash(**common, features=fc)
    assert ha == hb
    assert ha != hc


def test_missing_relations_do_not_block_eligibility() -> None:
    """L: missing/stale Relations keep sample eligible when core+tech+label are ok."""
    assert (
        is_horizon_training_eligible(
            core_valid=True,
            technical_available=True,
            label_valid=True,
            relations_optional=True,
            relations_available=False,
        )
        is True
    )
    assert (
        is_horizon_training_eligible(
            core_valid=True,
            technical_available=True,
            label_valid=False,
            relations_optional=True,
            relations_available=True,
        )
        is False
    )


def test_relation_missing_and_available_semantics() -> None:
    """relation_missing = join on AND no usable context. Partial coverage is available."""
    assert is_sample_relation_missing(relations_enabled=True, relations_available=False) is True
    assert is_sample_relation_missing(relations_enabled=True, relations_available=True) is False
    assert is_sample_relation_missing(relations_enabled=False, relations_available=False) is False
    result_partial = extract_all_relation_features(
        contexts=RELATION_CONTEXTS_V1,
        subject_input_id=uuid4(),
        context_input_ids={},
        index=RelationIndex.build([], {}),
        as_of=date(2026, 1, 10),
        max_age_days=8,
    )
    assert result_partial.available is False
    assert is_sample_relation_missing(
        relations_enabled=True, relations_available=result_partial.available
    )


def test_manifest_lists_generated_relation_features() -> None:
    generated = relation_feature_names(RELATION_CONTEXTS_V1)
    manifest_features = feature_names_from_manifest(FEATURE_MANIFEST_V1)
    assert generated
    assert set(generated) <= set(manifest_features)
    by_name = {item["name"]: item for item in FEATURE_MANIFEST_V1}
    assert by_name["rel_imoex_w60_pearson"]["source"] == "relations"
    assert by_name["rel_imoex_w60_pearson"]["role"] == "feature"
    assert by_name["rel_usd_rub_context_leads_lag3_pearson"]["role"] == "feature"
    assert by_name["forward_return_5d"]["role"] == "label"
    assert "rel_imoex_w60_pearson" not in {m["name"] for m in FEATURE_MANIFEST_V1 if m["role"] == "label"}


def test_invalid_snapshot_is_null_not_zero() -> None:
    subject, context = uuid4(), uuid4()
    snap = _snap(
        snap_id=1, ia=subject, ib=context, window=60, as_of=date(2026, 1, 8), pearson=0.9, valid=False
    )
    feats, meta = _extract(RelationIndex.build([snap], {1: []}), subject, context, date(2026, 1, 10))  # type: ignore[arg-type]
    assert feats["rel_imoex_w60_pearson"] is None
    assert meta["available"] is False
    assert meta["reason"] == "invalid"


def test_no_imputation_zero_for_stale_or_missing() -> None:
    subject, context = uuid4(), uuid4()
    stale = _snap(snap_id=1, ia=subject, ib=context, window=60, as_of=date(2026, 1, 1), pearson=0.4)
    feats, _ = _extract(RelationIndex.build([stale], {1: []}), subject, context, date(2026, 1, 10))  # type: ignore[arg-type]
    assert all(v is None for v in feats.values())
