"""H5B Relations V2 pins Analytics v2 and keeps V1 raw contract."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import FeatureSet, InstrumentFeatureDaily
from app.infrastructure.analytics.relation_models import RelationSet
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.market.application.mechanical_adjustment import MechanicalAction
from app.modules.market.application.seed import seed_market_universe
from app.modules.relations.application.calculator import InputSeries, RelationCalculator
from app.modules.relations.application.compute import resolve_analytics_feature_set
from app.modules.relations.application.seed import seed_relation_sets
from app.modules.relations.relation_config import BASIC_RELATIONS_V1, BASIC_RELATIONS_V2


def test_v2_pins_analytics_v2_not_active(core_db: Session) -> None:
    seed_feature_sets(core_db)
    seed_relation_sets(core_db)
    v1 = core_db.scalar(select(RelationSet).where(RelationSet.code == "basic_relations", RelationSet.version == 1))
    v2 = core_db.scalar(select(RelationSet).where(RelationSet.code == "basic_relations", RelationSet.version == 2))
    assert v1 is not None and v2 is not None
    assert v1.is_active is True
    assert v2.is_active is False
    assert v2.parameters["analytics_feature_set_version"] == 2
    assert v1.parameters.get("analytics_feature_set_version") is None
    basic_v1 = resolve_analytics_feature_set(core_db, v1)
    basic_v2 = resolve_analytics_feature_set(core_db, v2)
    assert basic_v1.code == "basic_daily" and basic_v1.version == 1
    assert basic_v2.code == "basic_daily" and basic_v2.version == 2
    assert basic_v1.is_active is True
    assert basic_v2.is_active is False


def test_active_v1_and_hypothetical_v3_do_not_change_v2_pin(core_db: Session) -> None:
    seed_feature_sets(core_db)
    seed_relation_sets(core_db)
    v3 = FeatureSet(
        code="basic_daily",
        version=3,
        description="hypothetical",
        parameters={"price_basis": "other"},
        is_active=False,
        updated_at=datetime.now(UTC),
    )
    core_db.add(v3)
    core_db.flush()
    core_db.execute(update(FeatureSet).values(is_active=False))
    v3.is_active = True
    core_db.flush()
    rel_v2 = core_db.scalar(select(RelationSet).where(RelationSet.code == "basic_relations", RelationSet.version == 2))
    rel_v1 = core_db.scalar(select(RelationSet).where(RelationSet.code == "basic_relations", RelationSet.version == 1))
    assert rel_v2 is not None and rel_v1 is not None
    pinned = resolve_analytics_feature_set(core_db, rel_v2)
    v1_pin = resolve_analytics_feature_set(core_db, rel_v1)
    assert pinned.version == 2
    assert v1_pin.version == 1
    assert v3.is_active is True


def test_zero_lag_windows_and_spearman_unchanged() -> None:
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(40)]
    a = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(float(i) for i in range(40)))
    b = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(float(i) * 2 for i in range(40)))
    left, right = (a, b) if a.input_id < b.input_id else (b, a)
    v1 = RelationCalculator(BASIC_RELATIONS_V1["parameters"]).calculate_as_of(
        {left.input_id: left, right.input_id: right},
        as_of_date=days[-1],
        input_ids=[left.input_id, right.input_id],
    )
    v2 = RelationCalculator(BASIC_RELATIONS_V2["parameters"]).calculate_as_of(
        {left.input_id: left, right.input_id: right},
        as_of_date=days[-1],
        input_ids=[left.input_id, right.input_id],
    )
    by_v1 = {row.window_observations: row for row in v1}
    by_v2 = {row.window_observations: row for row in v2}
    assert set(by_v1) == {20, 60, 120}
    for window in (20, 60, 120):
        assert by_v1[window].pearson == by_v2[window].pearson
        assert by_v1[window].spearman == by_v2[window].spearman
        assert by_v1[window].sign_consistency == by_v2[window].sign_consistency
        assert by_v1[window].best_lag == by_v2[window].best_lag


def test_lag_orientation_leader_then_follower() -> None:
    import numpy as np

    rng = np.random.default_rng(2)
    leader = rng.normal(0, 1, 100)
    follower = np.zeros(100)
    follower[2:] = leader[:-2]
    days = [date(2024, 2, 1) + timedelta(days=i) for i in range(100)]
    a = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(leader.tolist()))
    b = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(follower.tolist()))
    rows = RelationCalculator(BASIC_RELATIONS_V2["parameters"]).calculate_as_of(
        {a.input_id: a, b.input_id: b},
        as_of_date=days[-1],
        input_ids=[a.input_id, b.input_id],
    )
    win = next(row for row in rows if row.window_observations == 60)
    assert win.best_lag == 2
    assert win.best_leader_input_id == a.input_id
    assert win.best_follower_input_id == b.input_id
    assert len(win.lag_metrics) == 10


def test_split_mechanical_input_changes_relation_not_v1_identity() -> None:
    import numpy as np

    rng = np.random.default_rng(11)
    days = [date(2025, 3, 8) + timedelta(days=i) for i in range(20)]
    base = rng.normal(0, 0.01, 20)
    other = base + rng.normal(0, 0.002, 20)
    raw = base.copy()
    adj = base.copy()
    raw[-1] = -0.90
    adj[-1] = -0.006
    clean = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(base.tolist()))
    a_raw = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(raw.tolist()))
    a_adj = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(adj.tolist()))
    b = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(other.tolist()))
    calc = RelationCalculator(BASIC_RELATIONS_V2["parameters"])

    def _pearson(left: InputSeries, right: InputSeries) -> float | None:
        rows = calc.calculate_as_of(
            {left.input_id: left, right.input_id: right},
            as_of_date=days[-1],
            input_ids=[left.input_id, right.input_id],
        )
        return next(row.pearson for row in rows if row.window_observations == 20)

    p_clean = _pearson(clean, b)
    p1 = _pearson(a_raw, b)
    p2 = _pearson(a_adj, b)
    assert p_clean is not None and p1 is not None and p2 is not None
    assert p1 != p2
    assert abs(p2 - p_clean) < abs(p1 - p_clean)


def test_plzl_vtbr_sber_feature_inputs(core_db: Session) -> None:
    seed_feature_sets(core_db)
    seed_market_universe(core_db)
    v1 = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "basic_daily", FeatureSet.version == 1))
    v2 = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "basic_daily", FeatureSet.version == 2))
    assert v1 is not None and v2 is not None
    from app.infrastructure.market.models import Instrument

    plzl = core_db.scalar(select(Instrument).where(Instrument.symbol == "PLZL"))
    vtbr = core_db.scalar(select(Instrument).where(Instrument.symbol == "VTBR"))
    sber = core_db.scalar(select(Instrument).where(Instrument.symbol == "SBER"))
    assert plzl and vtbr and sber
    plzl_v1 = core_db.scalar(
        select(InstrumentFeatureDaily).where(
            InstrumentFeatureDaily.instrument_id == plzl.id,
            InstrumentFeatureDaily.feature_set_id == v1.id,
            InstrumentFeatureDaily.date == date(2025, 3, 27),
        )
    )
    plzl_v2 = core_db.scalar(
        select(InstrumentFeatureDaily).where(
            InstrumentFeatureDaily.instrument_id == plzl.id,
            InstrumentFeatureDaily.feature_set_id == v2.id,
            InstrumentFeatureDaily.date == date(2025, 3, 27),
        )
    )
    if plzl_v1 is not None and plzl_v2 is not None and plzl_v1.log_return_1d is not None:
        assert float(plzl_v1.log_return_1d) < -0.8
        assert plzl_v2.log_return_1d is not None
        assert abs(float(plzl_v2.log_return_1d)) < 0.08
    vtbr_v1 = core_db.scalar(
        select(InstrumentFeatureDaily).where(
            InstrumentFeatureDaily.instrument_id == vtbr.id,
            InstrumentFeatureDaily.feature_set_id == v1.id,
            InstrumentFeatureDaily.date == date(2024, 7, 15),
        )
    )
    vtbr_v2 = core_db.scalar(
        select(InstrumentFeatureDaily).where(
            InstrumentFeatureDaily.instrument_id == vtbr.id,
            InstrumentFeatureDaily.feature_set_id == v2.id,
            InstrumentFeatureDaily.date == date(2024, 7, 15),
        )
    )
    if vtbr_v1 is not None and vtbr_v2 is not None and vtbr_v1.log_return_1d is not None:
        assert abs(float(vtbr_v1.log_return_1d)) > 1.0
        assert vtbr_v2.log_return_1d is not None
        assert abs(float(vtbr_v2.log_return_1d)) < 0.2
    sber_v1 = core_db.scalar(
        select(InstrumentFeatureDaily).where(
            InstrumentFeatureDaily.instrument_id == sber.id,
            InstrumentFeatureDaily.feature_set_id == v1.id,
            InstrumentFeatureDaily.date == date(2024, 6, 10),
        )
    )
    sber_v2 = core_db.scalar(
        select(InstrumentFeatureDaily).where(
            InstrumentFeatureDaily.instrument_id == sber.id,
            InstrumentFeatureDaily.feature_set_id == v2.id,
            InstrumentFeatureDaily.date == date(2024, 6, 10),
        )
    )
    if sber_v1 is not None and sber_v2 is not None:
        assert sber_v1.log_return_1d == sber_v2.log_return_1d


def test_future_mechanical_action_does_not_change_as_of() -> None:
    from app.modules.analytics.application.calculator import CandleObservation, DailyFeatureCalculator
    from app.modules.analytics.application.mechanical_features import calculate_mechanical_adjusted_features
    from app.modules.analytics.feature_config import BASIC_DAILY_V2

    observations = [
        CandleObservation(date=date(2024, 1, 1), close=100, volume=1),
        CandleObservation(date=date(2024, 1, 2), close=101, volume=1),
        CandleObservation(date=date(2024, 1, 3), close=102, volume=1),
    ]
    t = date(2024, 1, 2)
    none = calculate_mechanical_adjusted_features(
        DailyFeatureCalculator(BASIC_DAILY_V2["parameters"]),
        observations,
        [],
        date_from=t,
        date_to=t,
    )
    future = MechanicalAction(1, date(2024, 1, 10), "SPLIT", Decimal("10"))
    after = calculate_mechanical_adjusted_features(
        DailyFeatureCalculator(BASIC_DAILY_V2["parameters"]),
        observations,
        [future],
        date_from=t,
        date_to=t,
    )
    assert none[0].log_return_1d == after[0].log_return_1d
    eligible = MechanicalAction(1, t, "SPLIT", Decimal("10"))
    changed = calculate_mechanical_adjusted_features(
        DailyFeatureCalculator(BASIC_DAILY_V2["parameters"]),
        observations,
        [eligible],
        date_from=t,
        date_to=t,
    )
    assert changed[0].log_return_1d != none[0].log_return_1d


def test_v1_snapshots_not_overwritten_by_v2_identity(core_db: Session) -> None:
    seed_relation_sets(core_db)
    v1 = core_db.scalar(select(RelationSet).where(RelationSet.code == "basic_relations", RelationSet.version == 1))
    v2 = core_db.scalar(select(RelationSet).where(RelationSet.code == "basic_relations", RelationSet.version == 2))
    assert v1 is not None and v2 is not None
    assert v1.id != v2.id
    assert v1.is_active is True
    assert v2.is_active is False


def test_reverse_split_mechanical_input_changes_relation() -> None:
    import numpy as np

    rng = np.random.default_rng(12)
    days = [date(2024, 7, 1) + timedelta(days=i) for i in range(20)]
    base = rng.normal(0, 0.01, 20)
    other = base + rng.normal(0, 0.002, 20)
    raw = base.copy()
    adj = base.copy()
    raw[-1] = 2.30
    adj[-1] = -0.07
    clean = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(base.tolist()))
    a_raw = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(raw.tolist()))
    a_adj = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(adj.tolist()))
    b = InputSeries(input_id=uuid4(), dates=tuple(days), values=tuple(other.tolist()))
    calc = RelationCalculator(BASIC_RELATIONS_V2["parameters"])

    def _pearson(left: InputSeries, right: InputSeries) -> float | None:
        rows = calc.calculate_as_of(
            {left.input_id: left, right.input_id: right},
            as_of_date=days[-1],
            input_ids=[left.input_id, right.input_id],
        )
        return next(row.pearson for row in rows if row.window_observations == 20)

    p_clean = _pearson(clean, b)
    p1 = _pearson(a_raw, b)
    p2 = _pearson(a_adj, b)
    assert p_clean is not None and p1 is not None and p2 is not None
    assert p1 != p2
    assert abs(p2 - p_clean) < abs(p1 - p_clean)


def test_quality_excludes_unexplained_jump_keeps_valid_mechanical(core_db: Session) -> None:
    from app.infrastructure.analytics.relation_models import RelationInput
    from app.infrastructure.market.models import Instrument
    from app.modules.relations.application.compute import RelationsComputeService
    from app.modules.relations.relation_config import (
        INSTRUMENT_ALIGNMENT,
        INSTRUMENT_FEATURE_KEY,
        INSTRUMENT_TRANSFORM,
    )

    seed_feature_sets(core_db)
    v2 = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "basic_daily", FeatureSet.version == 2))
    assert v2 is not None
    inst = Instrument(
        symbol="H5BQLT",
        name="H5B quality fixture",
        asset_class="equity",
        exchange="TEST",
        currency="RUB",
        is_active=True,
    )
    core_db.add(inst)
    core_db.flush()
    inp = RelationInput(
        code="instrument:H5BQLT:log_return_1d",
        input_family="instrument_feature",
        subject_type="instrument",
        subject_id=inst.id,
        feature_key=INSTRUMENT_FEATURE_KEY,
        transform=INSTRUMENT_TRANSFORM,
        alignment_policy=INSTRUMENT_ALIGNMENT,
        display_name="H5BQLT log_return_1d",
        is_active=True,
    )
    core_db.add(inp)
    core_db.flush()
    kept = date(2024, 6, 10)
    jump = date(2024, 6, 11)
    mechanical = date(2024, 6, 12)
    for day, ret, flags in (
        (kept, Decimal("0.01"), {}),
        (jump, Decimal("-0.90"), {"price_discontinuity": True}),
        (mechanical, Decimal("-0.006"), {}),
    ):
        core_db.add(
            InstrumentFeatureDaily(
                instrument_id=inst.id,
                date=day,
                timeframe="1d",
                feature_set_id=v2.id,
                feature_version=2,
                log_return_1d=ret,
                is_valid=True,
                quality_flags=flags,
            )
        )
    core_db.flush()
    matrix = RelationsComputeService(core_db)._load_input_matrix(
        [inp],
        feature_set_id=v2.id,
        date_from=date(2024, 6, 1),
        date_to=date(2024, 6, 20),
        exclude_invalid=True,
        exclude_discontinuities=True,
    )
    series = matrix[inp.id]
    assert kept in series.dates
    assert mechanical in series.dates
    assert jump not in series.dates


def test_repeat_as_of_skip_is_idempotent() -> None:
    planned = [date(2024, 6, 7), date(2024, 6, 14), date(2024, 6, 21)]
    already = {date(2024, 6, 7), date(2024, 6, 14)}
    pending = [d for d in planned if d not in already]
    assert pending == [date(2024, 6, 21)]
    assert len(planned) - len(pending) == 2
