"""H4A Analytics V2 mechanical-adjusted features."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import FeatureSet, InstrumentFeatureDaily
from app.infrastructure.market.models import Candle, Instrument
from app.modules.analytics.application.calculator import CandleObservation, DailyFeatureCalculator
from app.modules.analytics.application.compute import FeatureComputeService
from app.modules.analytics.application.mechanical_features import calculate_mechanical_adjusted_features
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.analytics.feature_config import BASIC_DAILY_V1, BASIC_DAILY_V2
from app.modules.market.application.mechanical_adjustment import MechanicalAction, load_mechanical_actions
from app.modules.market.application.split_events import EVENT_TYPE_REVERSE_SPLIT, EVENT_TYPE_SPLIT


def _obs(day: date, close: float, volume: float = 100.0) -> CandleObservation:
    return CandleObservation(date=day, close=close, volume=volume)


def test_plzl_real_split_is_not_a_crash(core_db: Session) -> None:
    inst = core_db.scalar(select(Instrument).where(Instrument.symbol == "PLZL"))
    assert inst is not None
    before = datetime(2025, 3, 26, tzinfo=UTC)
    after = datetime(2025, 3, 27, tzinfo=UTC)
    raw_before = core_db.scalar(select(Candle).where(Candle.instrument_id == inst.id, Candle.timestamp == before))
    raw_after = core_db.scalar(select(Candle).where(Candle.instrument_id == inst.id, Candle.timestamp == after))
    assert raw_before is not None and raw_after is not None
    raw_return = float(raw_after.close / raw_before.close - 1)
    assert raw_return < -0.8

    candles = list(
        core_db.scalars(
            select(Candle)
            .where(
                Candle.instrument_id == inst.id,
                Candle.timestamp >= datetime(2025, 3, 1, tzinfo=UTC),
                Candle.timestamp <= datetime(2025, 3, 31, tzinfo=UTC),
            )
            .order_by(Candle.timestamp)
        )
    )
    observations = [
        CandleObservation(
            date=row.timestamp.date(),
            close=float(row.close),
            volume=float(row.volume) if row.volume is not None else None,
        )
        for row in candles
    ]
    raw_rows = DailyFeatureCalculator(BASIC_DAILY_V1["parameters"]).calculate(
        observations, date_from=date(2025, 3, 27), date_to=date(2025, 3, 27)
    )
    adj_rows = calculate_mechanical_adjusted_features(
        DailyFeatureCalculator(BASIC_DAILY_V2["parameters"]),
        observations,
        load_mechanical_actions(core_db, inst.id),
        date_from=date(2025, 3, 27),
        date_to=date(2025, 3, 27),
    )
    assert raw_rows[0].return_1d is not None and raw_rows[0].return_1d < -0.8
    assert adj_rows[0].return_1d is not None
    assert abs(adj_rows[0].return_1d) < 0.08
    assert adj_rows[0].quality_flags.get("price_discontinuity") is not True


def test_vtbr_reverse_split_generic(core_db: Session) -> None:
    inst = core_db.scalar(select(Instrument).where(Instrument.symbol == "VTBR"))
    assert inst is not None
    loaded = load_mechanical_actions(core_db, inst.id)
    actions = [item for item in loaded if item.event_type == EVENT_TYPE_REVERSE_SPLIT]
    assert actions
    event_day = actions[0].event_date
    candles = list(
        core_db.scalars(
            select(Candle)
            .where(
                Candle.instrument_id == inst.id,
                Candle.timestamp >= datetime(event_day.year, event_day.month, 1, tzinfo=UTC),
                Candle.timestamp <= datetime(event_day.year, event_day.month, 28, tzinfo=UTC),
            )
            .order_by(Candle.timestamp)
        )
    )
    observations = [
        CandleObservation(date=row.timestamp.date(), close=float(row.close), volume=None) for row in candles
    ]
    raw_rows = DailyFeatureCalculator(BASIC_DAILY_V1["parameters"]).calculate(
        observations, date_from=event_day, date_to=event_day
    )
    adj_rows = calculate_mechanical_adjusted_features(
        DailyFeatureCalculator(BASIC_DAILY_V2["parameters"]),
        observations,
        load_mechanical_actions(core_db, inst.id),
        date_from=event_day,
        date_to=event_day,
    )
    assert raw_rows and adj_rows
    assert raw_rows[0].return_1d is not None and abs(raw_rows[0].return_1d) > 0.5
    assert adj_rows[0].return_1d is not None and abs(adj_rows[0].return_1d) < 0.2


def test_sber_control_matches_raw(core_db: Session) -> None:
    inst = core_db.scalar(select(Instrument).where(Instrument.symbol == "SBER"))
    assert inst is not None
    day = date(2024, 6, 10)
    candles = list(
        core_db.scalars(
            select(Candle)
            .where(
                Candle.instrument_id == inst.id,
                Candle.timestamp >= datetime(2024, 5, 1, tzinfo=UTC),
                Candle.timestamp <= datetime(2024, 6, 15, tzinfo=UTC),
            )
            .order_by(Candle.timestamp)
        )
    )
    observations = [
        CandleObservation(date=row.timestamp.date(), close=float(row.close), volume=float(row.volume or 0))
        for row in candles
    ]
    raw_rows = DailyFeatureCalculator(BASIC_DAILY_V1["parameters"]).calculate(
        observations, date_from=day, date_to=day
    )
    adj_rows = calculate_mechanical_adjusted_features(
        DailyFeatureCalculator(BASIC_DAILY_V2["parameters"]),
        observations,
        load_mechanical_actions(core_db, inst.id),
        date_from=day,
        date_to=day,
    )
    assert raw_rows and adj_rows
    assert raw_rows[0].return_1d is not None
    assert adj_rows[0].return_1d is not None
    assert abs(raw_rows[0].return_1d - adj_rows[0].return_1d) < 1e-12


def test_multiple_actions_and_future_split_is_pit(core_db: Session) -> None:
    observations = [
        _obs(date(2020, 1, 1), 100),
        _obs(date(2020, 1, 2), 110),
        _obs(date(2020, 1, 3), 55),
        _obs(date(2020, 1, 4), 60),
    ]
    first = MechanicalAction(1, date(2020, 1, 3), EVENT_TYPE_SPLIT, Decimal("2"))
    future = MechanicalAction(1, date(2020, 1, 10), EVENT_TYPE_SPLIT, Decimal("10"))
    calc = DailyFeatureCalculator(BASIC_DAILY_V2["parameters"])
    before_future = calculate_mechanical_adjusted_features(
        calc, observations, [first], date_from=date(2020, 1, 2), date_to=date(2020, 1, 4)
    )
    after_future = calculate_mechanical_adjusted_features(
        calc, observations, [first, future], date_from=date(2020, 1, 2), date_to=date(2020, 1, 4)
    )
    by_before = {row.date: row.return_1d for row in before_future}
    by_after = {row.date: row.return_1d for row in after_future}
    assert by_before[date(2020, 1, 2)] == by_after[date(2020, 1, 2)]
    assert by_before[date(2020, 1, 3)] is not None
    assert abs(by_before[date(2020, 1, 3)] - 0.0) < 1e-9
    assert by_before[date(2020, 1, 3)] == by_after[date(2020, 1, 3)]


def test_dividend_event_is_not_adjusted() -> None:
    observations = [_obs(date(2021, 6, 1), 100), _obs(date(2021, 6, 2), 90)]
    rows = calculate_mechanical_adjusted_features(
        DailyFeatureCalculator(BASIC_DAILY_V2["parameters"]),
        observations,
        [],
        date_from=date(2021, 6, 2),
        date_to=date(2021, 6, 2),
    )
    assert rows[0].return_1d is not None
    assert abs(rows[0].return_1d - (-0.1)) < 1e-12


def test_v1_unchanged_and_v2_coexists(core_db: Session) -> None:
    seed_feature_sets(core_db)
    v1 = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "basic_daily", FeatureSet.version == 1))
    v2 = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "basic_daily", FeatureSet.version == 2))
    assert v1 is not None and v2 is not None
    assert v1.is_active is True
    assert v2.is_active is False
    assert v1.parameters.get("price_basis") != "mechanical_adjusted"
    assert v2.parameters.get("price_basis") == "mechanical_adjusted"

    inst = core_db.scalar(select(Instrument).where(Instrument.symbol == "PLZL"))
    assert inst is not None
    v1_before = core_db.scalar(
        select(InstrumentFeatureDaily).where(
            InstrumentFeatureDaily.instrument_id == inst.id,
            InstrumentFeatureDaily.feature_set_id == v1.id,
            InstrumentFeatureDaily.date == date(2025, 3, 27),
        )
    )
    FeatureComputeService(core_db).run_backfill(
        date_from=date(2025, 3, 20),
        date_to=date(2025, 3, 28),
        feature_set_code="basic_daily",
        feature_set_version=2,
    )
    v1_after = core_db.scalar(
        select(InstrumentFeatureDaily).where(
            InstrumentFeatureDaily.instrument_id == inst.id,
            InstrumentFeatureDaily.feature_set_id == v1.id,
            InstrumentFeatureDaily.date == date(2025, 3, 27),
        )
    )
    v2_row = core_db.scalar(
        select(InstrumentFeatureDaily).where(
            InstrumentFeatureDaily.instrument_id == inst.id,
            InstrumentFeatureDaily.feature_set_id == v2.id,
            InstrumentFeatureDaily.date == date(2025, 3, 27),
        )
    )
    if v1_before is not None:
        assert v1_after is not None
        assert v1_before.return_1d == v1_after.return_1d
    assert v2_row is not None
    assert v2_row.return_1d is not None
    assert abs(v2_row.return_1d) < 0.08


def test_eligible_action_changes_history_after_effective_date() -> None:
    observations = [_obs(date(2020, 1, 1), 100), _obs(date(2020, 1, 2), 50)]
    calc = DailyFeatureCalculator(BASIC_DAILY_V2["parameters"])
    none = calculate_mechanical_adjusted_features(
        calc, observations, [], date_from=date(2020, 1, 2), date_to=date(2020, 1, 2)
    )
    split = MechanicalAction(1, date(2020, 1, 2), EVENT_TYPE_SPLIT, Decimal("2"))
    adj = calculate_mechanical_adjusted_features(
        calc, observations, [split], date_from=date(2020, 1, 2), date_to=date(2020, 1, 2)
    )
    assert none[0].return_1d == -0.5
    assert adj[0].return_1d == 0.0
