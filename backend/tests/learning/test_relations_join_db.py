"""DB integration: Relations V1 snapshots → Dataset PIT join (no full builder)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.infrastructure.analytics.relation_models import (
    RelationInput,
    RelationLagMetric,
    RelationRun,
    RelationSet,
    RelationSnapshot,
)
from app.infrastructure.analytics.relation_repository import (
    load_lag_metrics_for_snapshots,
    load_pinned_relation_set,
    load_relation_inputs_by_codes,
    load_relation_snapshots_for_join,
)
from app.modules.learning.application.relations_join import (
    RelationIndex,
    extract_all_relation_features,
    extract_relation_features,
)


def _input(session: Session, *, code: str, subject_id: int) -> RelationInput:
    row = RelationInput(
        code=code,
        input_family="instrument_feature" if code.startswith("instrument:") else "series_feature",
        subject_type="instrument" if code.startswith("instrument:") else "series",
        subject_id=subject_id,
        feature_key="log_return_1d" if code.startswith("instrument:") else "pct_change",
        transform="test",
        alignment_policy="test",
        display_name=code,
        is_active=True,
    )
    session.add(row)
    session.flush()
    return row


def _set(session: Session, *, code: str, version: int) -> RelationSet:
    row = RelationSet(
        code=code,
        version=version,
        description=f"{code} v{version} join test",
        parameters={"windows": [20, 60, 120]},
        is_active=version == 1,
    )
    session.add(row)
    session.flush()
    return row


def _run(session: Session, relation_set: RelationSet) -> RelationRun:
    row = RelationRun(
        relation_set_id=relation_set.id,
        run_type="LATEST",
        status="SUCCESS",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def _snapshot(
    session: Session,
    *,
    run: RelationRun,
    relation_set: RelationSet,
    as_of: date,
    window: int,
    input_a: RelationInput,
    input_b: RelationInput,
    pearson: float,
    spearman: float = 0.2,
    rolling: float = 0.05,
    sign: float = 0.8,
    valid: bool = True,
) -> RelationSnapshot:
    a, b = (input_a, input_b) if input_a.id < input_b.id else (input_b, input_a)
    row = RelationSnapshot(
        relation_run_id=run.id,
        relation_set_id=relation_set.id,
        relation_set_version=relation_set.version,
        as_of_date=as_of,
        window_observations=window,
        input_a_id=a.id,
        input_b_id=b.id,
        sample_count=60,
        pearson=pearson,
        spearman=spearman,
        rolling_corr_std=rolling,
        sign_consistency=sign,
        is_valid=valid,
        quality_flags={},
    )
    session.add(row)
    session.flush()
    return row


def test_repository_pit_join_and_version_pin(core_db: Session) -> None:
    v1 = _set(core_db, code="dataset_pit_join_test", version=1)
    v2 = _set(core_db, code="dataset_pit_join_test", version=2)
    run1 = _run(core_db, v1)
    run2 = _run(core_db, v2)

    subject = _input(core_db, code="instrument:PITJOIN1:log_return_1d", subject_id=9101)
    imoex = _input(core_db, code="instrument:PITJOINIMOEX:log_return_1d", subject_id=9102)
    usd = _input(core_db, code="series:PITJOINUSD:pct_change", subject_id=9201)

    s_jan1 = _snapshot(
        core_db, run=run1, relation_set=v1, as_of=date(2026, 1, 1), window=60,
        input_a=subject, input_b=imoex, pearson=0.11,
    )
    s_jan8 = _snapshot(
        core_db, run=run1, relation_set=v1, as_of=date(2026, 1, 8), window=60,
        input_a=subject, input_b=imoex, pearson=0.22, spearman=0.25, rolling=0.07, sign=0.66,
    )
    _snapshot(
        core_db, run=run1, relation_set=v1, as_of=date(2026, 1, 15), window=60,
        input_a=subject, input_b=imoex, pearson=0.99,
    )
    _snapshot(
        core_db, run=run2, relation_set=v2, as_of=date(2026, 1, 8), window=60,
        input_a=subject, input_b=imoex, pearson=0.88,
    )
    w20 = _snapshot(
        core_db, run=run1, relation_set=v1, as_of=date(2026, 1, 8), window=20,
        input_a=subject, input_b=imoex, pearson=0.21, spearman=0.22,
    )
    w120 = _snapshot(
        core_db, run=run1, relation_set=v1, as_of=date(2026, 1, 8), window=120,
        input_a=subject, input_b=imoex, pearson=0.12, spearman=0.13,
    )

    core_db.add_all(
        [
            RelationLagMetric(
                snapshot_id=s_jan8.id,
                leader_input_id=subject.id,
                follower_input_id=imoex.id,
                lag=3,
                pearson=0.77,
                sample_count=50,
            ),
            RelationLagMetric(
                snapshot_id=s_jan8.id,
                leader_input_id=imoex.id,
                follower_input_id=subject.id,
                lag=3,
                pearson=-0.33,
                sample_count=50,
            ),
        ]
    )
    core_db.flush()

    pinned = load_pinned_relation_set(core_db, "dataset_pit_join_test", 1)
    assert pinned is not None and pinned.id == v1.id
    assert pinned.version == 1
    active_v2_id = v2.id
    assert pinned.id != active_v2_id

    inputs = load_relation_inputs_by_codes(
        core_db,
        ["instrument:PITJOIN1:log_return_1d", "instrument:PITJOINIMOEX:log_return_1d", "series:PITJOINUSD:pct_change"],
    )
    assert set(inputs) == {
        "instrument:PITJOIN1:log_return_1d",
        "instrument:PITJOINIMOEX:log_return_1d",
        "series:PITJOINUSD:pct_change",
    }

    snapshots = load_relation_snapshots_for_join(
        core_db,
        relation_set_id=pinned.id,
        relation_set_version=1,
        pair_ids=[(subject.id, imoex.id), (subject.id, usd.id)],
        windows=[20, 60, 120],
        date_from=date(2026, 1, 10),
        date_to=date(2026, 1, 10),
        lookback_days=9,
    )
    assert {s.id for s in snapshots} >= {s_jan1.id, s_jan8.id, w20.id, w120.id}
    assert all(s.relation_set_version == 1 for s in snapshots)
    assert all(s.as_of_date <= date(2026, 1, 10) for s in snapshots)
    assert 0.88 not in {float(s.pearson) for s in snapshots if s.pearson is not None}

    lags = load_lag_metrics_for_snapshots(core_db, [s.id for s in snapshots])
    index = RelationIndex.build(snapshots, lags)

    feats, meta = extract_relation_features(
        context_key="imoex",
        subject_input_id=subject.id,
        context_input_id=imoex.id,
        windows=[20, 60, 120],
        lag_window=60,
        lags=[1, 2, 3, 4, 5],
        index=index,
        as_of=date(2026, 1, 10),
        max_age_days=8,
    )
    assert feats["rel_imoex_w60_pearson"] == 0.22
    assert feats["rel_imoex_w60_spearman"] == 0.25
    assert feats["rel_imoex_w20_pearson"] == 0.21
    assert feats["rel_imoex_w120_pearson"] == 0.12
    assert feats["rel_imoex_w60_rolling_corr_std"] == 0.07
    assert feats["rel_imoex_w60_sign_consistency"] == 0.66
    assert feats["rel_imoex_subject_leads_lag3_pearson"] == 0.77
    assert feats["rel_imoex_context_leads_lag3_pearson"] == -0.33
    assert meta["available"] is True
    assert meta["as_of_dates"]["60"] == "2026-01-08"

    joined = extract_all_relation_features(
        contexts=[
            {
                "key": "imoex",
                "input_code": "instrument:IMOEX:log_return_1d",
                "windows": [20, 60, 120],
                "lag_window": 60,
                "lags": [1, 2, 3, 4, 5],
            },
            {
                "key": "usd_rub",
                "input_code": "series:USD_RUB_CBR:pct_change",
                "windows": [20, 60, 120],
                "lag_window": 60,
                "lags": [1, 2, 3, 4, 5],
            },
        ],
        subject_input_id=subject.id,
        context_input_ids={"imoex": imoex.id, "usd_rub": usd.id},
        index=index,
        as_of=date(2026, 1, 10),
        max_age_days=8,
    )
    assert joined.available is True
    assert joined.features["rel_imoex_w60_pearson"] == 0.22
    assert joined.features["rel_usd_rub_w60_pearson"] is None
    assert joined.context_meta["usd_rub"]["available"] is False
    assert joined.available_context_count == 1
    assert joined.expected_context_count == 2


def test_self_relation_imoex_is_null_in_db_path(core_db: Session) -> None:
    v1 = _set(core_db, code="dataset_pit_join_self", version=1)
    run1 = _run(core_db, v1)
    imoex = _input(core_db, code="instrument:PITJOINSELF:log_return_1d", subject_id=9103)
    other = _input(core_db, code=f"instrument:PITJOINOTH:{uuid4().hex[:6]}", subject_id=9199)
    _snapshot(
        core_db, run=run1, relation_set=v1, as_of=date(2026, 1, 8), window=60,
        input_a=imoex, input_b=other, pearson=0.5,
    )
    index = RelationIndex.build([], {})
    feats, meta = extract_relation_features(
        context_key="imoex",
        subject_input_id=imoex.id,
        context_input_id=imoex.id,
        windows=[20, 60, 120],
        lag_window=60,
        lags=[1, 2, 3, 4, 5],
        index=index,
        as_of=date(2026, 1, 10),
        max_age_days=8,
    )
    assert meta["reason"] == "self_relation"
    assert all(v is None for v in feats.values())
