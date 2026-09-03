"""H5A Technical V2 mechanical-adjusted features and contract pins."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import FeatureSet, InstrumentFeatureDaily
from app.infrastructure.market.models import Candle, CorporateAction, Instrument
from app.infrastructure.ml.technical_rules import RuleBasedTechnicalModel
from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.market.application.mechanical_adjustment import MechanicalAction
from app.modules.market.application.seed import seed_market_universe
from app.modules.technical.application.calculator import OhlcObservation, TechnicalFeatureCalculator
from app.modules.technical.application.mechanical_technical import calculate_mechanical_adjusted_technical
from app.modules.technical.application.signal_service import TechnicalSignalService, feature_set_ref
from app.modules.technical.technical_config import (
    RULES_V1_CODE,
    RULES_V1_VERSION,
    RULES_V2_CONFIG,
    RULES_V2_VERSION,
    TECHNICAL_DAILY_V1,
    TECHNICAL_DAILY_V2,
    resolve_technical_contract,
)


def _ohlc(
    day: date,
    close: float,
    *,
    high: float | None = None,
    low: float | None = None,
    volume: float = 100.0,
) -> OhlcObservation:
    high = close if high is None else high
    low = close if low is None else low
    return OhlcObservation(date=day, open=close, high=high, low=low, close=close, volume=volume)


def _series(start: date, closes: list[float]) -> list[OhlcObservation]:
    return [_ohlc(start + timedelta(days=i), close) for i, close in enumerate(closes)]


def test_contract_pins_analytics_v2_not_active() -> None:
    contract = resolve_technical_contract(RULES_V1_CODE, RULES_V2_VERSION)
    assert contract["basic_code"] == "basic_daily"
    assert contract["basic_version"] == 2
    assert contract["technical_version"] == 2
    assert contract["price_basis"] == "mechanical_adjusted"
    v1 = resolve_technical_contract(RULES_V1_CODE, RULES_V1_VERSION)
    assert v1["basic_version"] == 1
    assert v1["technical_version"] == 1


def test_future_analytics_v3_does_not_change_v2_pin(core_db: Session) -> None:
    seed_feature_sets(core_db)
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
    contract = resolve_technical_contract(RULES_V1_CODE, RULES_V2_VERSION)
    from app.modules.analytics.application.resolve import resolve_feature_set

    pinned = resolve_feature_set(core_db, contract["basic_code"], contract["basic_version"])
    active = resolve_feature_set(core_db, "basic_daily", None)
    assert pinned.version == 2
    assert active.version == 3
    assert pinned.parameters.get("price_basis") == "mechanical_adjusted"


def test_split_adjusted_sma_ema_rsi_atr() -> None:
    start = date(2024, 1, 1)
    closes = [19000.0] * 20 + [1890.0]
    raw = _series(start, closes)
    split_day = start + timedelta(days=20)
    for obs in raw[:-1]:
        obs.high = obs.close + 50
        obs.low = obs.close - 50
    raw[-1].high = 1910
    raw[-1].low = 1870
    action = MechanicalAction(1, split_day, "SPLIT", Decimal("10"))
    raw_calc = TechnicalFeatureCalculator(TECHNICAL_DAILY_V1["parameters"])
    v1 = raw_calc.calculate(raw, date_from=split_day, date_to=split_day)
    v2 = calculate_mechanical_adjusted_technical(
        TechnicalFeatureCalculator(TECHNICAL_DAILY_V2["parameters"]),
        raw,
        [action],
        date_from=split_day,
        date_to=split_day,
    )
    assert v1 and v2
    assert v1[0].sma20 is not None and v1[0].sma20 > 15000
    assert v2[0].sma20 is not None and 1800 < v2[0].sma20 < 2100
    assert v1[0].sma20_distance is not None and v1[0].sma20_distance < -0.8
    assert v2[0].sma20_distance is not None and abs(v2[0].sma20_distance) < 0.05
    assert v2[0].ema20 is not None and v2[0].ema20 < 3000
    assert v1[0].rsi14 is not None
    assert v2[0].rsi14 is not None
    assert v1[0].atr14 is not None and v2[0].atr14 is not None
    assert v1[0].atr14 > v2[0].atr14 * 5
    assert v2[0].atr14_pct is not None and v2[0].atr14_pct < 0.2


def test_split_adjusted_rsi_is_not_a_synthetic_crash() -> None:
    start = date(2024, 1, 1)
    closes = [100.0 + ((-1) ** i) * 0.5 for i in range(20)] + [10.05]
    raw = _series(start, closes)
    split_day = start + timedelta(days=20)
    v1 = TechnicalFeatureCalculator(TECHNICAL_DAILY_V1["parameters"]).calculate(
        raw, date_from=split_day, date_to=split_day
    )
    v2 = calculate_mechanical_adjusted_technical(
        TechnicalFeatureCalculator(TECHNICAL_DAILY_V2["parameters"]),
        raw,
        [MechanicalAction(1, split_day, "SPLIT", Decimal("10"))],
        date_from=split_day,
        date_to=split_day,
    )
    assert v1[0].rsi14 is not None and v1[0].rsi14 < 20
    assert v2[0].rsi14 is not None and v2[0].rsi14 > 30


def test_volume_is_scaled_on_adjusted_ohlcv() -> None:
    obs = [_ohlc(date(2024, 1, 1), 100, volume=10.0), _ohlc(date(2024, 1, 2), 10, volume=10.0)]
    action = MechanicalAction(1, date(2024, 1, 2), "SPLIT", Decimal("10"))
    rows = calculate_mechanical_adjusted_technical(
        TechnicalFeatureCalculator(TECHNICAL_DAILY_V2["parameters"]),
        obs,
        [action],
        date_from=date(2024, 1, 1),
        date_to=date(2024, 1, 2),
    )
    assert rows
    # Volume is consumed from Analytics v2, not Technical columns; adjustment still
    # keeps the OHLCV observation internally consistent (price / factor, volume * factor).
    from app.modules.market.application.mechanical_adjustment import actions_as_of, adjust_ohlcv

    _o, _h, _l, close, volume = adjust_ohlcv(
        open_=100,
        high=100,
        low=100,
        close=100,
        volume=10,
        obs_date=date(2024, 1, 1),
        actions=actions_as_of([action], date(2024, 1, 2)),
    )
    assert close == 10
    assert volume == 100


def test_future_mechanical_action_does_not_change_xt() -> None:
    start = date(2024, 1, 1)
    raw = _series(start, [100.0 + i for i in range(25)])
    t = start + timedelta(days=20)
    none = calculate_mechanical_adjusted_technical(
        TechnicalFeatureCalculator(TECHNICAL_DAILY_V2["parameters"]),
        raw,
        [],
        date_from=t,
        date_to=t,
    )
    future = MechanicalAction(1, t + timedelta(days=5), "SPLIT", Decimal("10"))
    after = calculate_mechanical_adjusted_technical(
        TechnicalFeatureCalculator(TECHNICAL_DAILY_V2["parameters"]),
        raw,
        [future],
        date_from=t,
        date_to=t,
    )
    assert none[0].sma20 == after[0].sma20
    assert none[0].rsi14 == after[0].rsi14
    eligible = MechanicalAction(1, t, "SPLIT", Decimal("10"))
    changed = calculate_mechanical_adjusted_technical(
        TechnicalFeatureCalculator(TECHNICAL_DAILY_V2["parameters"]),
        raw,
        [eligible],
        date_from=t,
        date_to=t,
    )
    assert changed[0].sma20 != none[0].sma20


def test_sber_like_control_matches_raw() -> None:
    start = date(2024, 5, 1)
    raw = _series(start, [300.0 + (i % 5) for i in range(25)])
    t = start + timedelta(days=24)
    v1 = TechnicalFeatureCalculator(TECHNICAL_DAILY_V1["parameters"]).calculate(raw, date_from=t, date_to=t)
    v2 = calculate_mechanical_adjusted_technical(
        TechnicalFeatureCalculator(TECHNICAL_DAILY_V2["parameters"]),
        raw,
        [],
        date_from=t,
        date_to=t,
    )
    assert v1[0].sma20 == v2[0].sma20
    assert v1[0].ema20 == v2[0].ema20
    assert v1[0].rsi14 == v2[0].rsi14
    assert v1[0].atr14 == v2[0].atr14


def test_plzl_real_split_technical(core_db: Session) -> None:
    seed_market_universe(core_db)
    inst = core_db.scalar(select(Instrument).where(Instrument.symbol == "PLZL"))
    assert inst is not None
    split = date(2025, 3, 27)
    before = date(2025, 3, 26)
    candles = list(
        core_db.scalars(
            select(Candle)
            .where(
                Candle.instrument_id == inst.id,
                Candle.timestamp >= datetime(2025, 2, 20, tzinfo=UTC),
                Candle.timestamp <= datetime(2025, 4, 5, tzinfo=UTC),
            )
            .order_by(Candle.timestamp)
        )
    )
    if len(candles) < 21:
        day = split - timedelta(days=24)
        for i in range(24):
            _seed_candle(core_db, inst.id, day + timedelta(days=i), 19011.5)
        _seed_candle(core_db, inst.id, split, 1890.0)
        _seed_ca(core_db, inst.id, split, "SPLIT", "1", "10")
        candles = list(
            core_db.scalars(
                select(Candle)
                .where(
                    Candle.instrument_id == inst.id,
                    Candle.timestamp >= datetime(2025, 2, 20, tzinfo=UTC),
                    Candle.timestamp <= datetime(2025, 4, 5, tzinfo=UTC),
                )
                .order_by(Candle.timestamp)
            )
        )
    existing_ca = list(
        core_db.scalars(select(CorporateAction).where(CorporateAction.instrument_id == inst.id))
    )
    if not any(row.event_date == split for row in existing_ca):
        _seed_ca(core_db, inst.id, split, "SPLIT", "1", "10")
    observations = [
        OhlcObservation(
            date=row.timestamp.date(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume) if row.volume is not None else None,
        )
        for row in candles
    ]
    from app.modules.market.application.mechanical_adjustment import load_mechanical_actions

    v1 = TechnicalFeatureCalculator(TECHNICAL_DAILY_V1["parameters"]).calculate(
        observations, date_from=split, date_to=split
    )
    v2 = calculate_mechanical_adjusted_technical(
        TechnicalFeatureCalculator(TECHNICAL_DAILY_V2["parameters"]),
        observations,
        load_mechanical_actions(core_db, inst.id),
        date_from=split,
        date_to=split,
    )
    assert v1 and v2
    assert v1[0].sma20 is not None and v2[0].sma20 is not None
    assert v1[0].sma20 > 10000
    assert 1500 < v2[0].sma20 < 2500
    assert v2[0].sma20_distance is not None and abs(v2[0].sma20_distance) < 0.15
    _ = before


def test_vtbr_real_reverse_split_technical(core_db: Session) -> None:
    seed_market_universe(core_db)
    inst = core_db.scalar(select(Instrument).where(Instrument.symbol == "VTBR"))
    assert inst is not None
    event = date(2024, 7, 15)
    candles = list(
        core_db.scalars(
            select(Candle)
            .where(
                Candle.instrument_id == inst.id,
                Candle.timestamp >= datetime(2024, 6, 1, tzinfo=UTC),
                Candle.timestamp <= datetime(2024, 8, 1, tzinfo=UTC),
            )
            .order_by(Candle.timestamp)
        )
    )
    if len(candles) < 21:
        day = event - timedelta(days=24)
        for i in range(24):
            _seed_candle(core_db, inst.id, day + timedelta(days=i), 0.0234)
        _seed_candle(core_db, inst.id, event, 108.8)
        candles = list(
            core_db.scalars(
                select(Candle)
                .where(
                    Candle.instrument_id == inst.id,
                    Candle.timestamp >= datetime(2024, 6, 1, tzinfo=UTC),
                    Candle.timestamp <= datetime(2024, 8, 1, tzinfo=UTC),
                )
                .order_by(Candle.timestamp)
            )
        )
    existing_ca = list(
        core_db.scalars(select(CorporateAction).where(CorporateAction.instrument_id == inst.id))
    )
    if not any(row.event_type == "REVERSE_SPLIT" for row in existing_ca):
        _seed_ca(core_db, inst.id, event, "REVERSE_SPLIT", "5000", "1")
    observations = [
        OhlcObservation(
            date=row.timestamp.date(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
        )
        for row in candles
    ]
    from app.modules.market.application.mechanical_adjustment import load_mechanical_actions

    v1 = TechnicalFeatureCalculator(TECHNICAL_DAILY_V1["parameters"]).calculate(
        observations, date_from=event, date_to=event
    )
    v2 = calculate_mechanical_adjusted_technical(
        TechnicalFeatureCalculator(TECHNICAL_DAILY_V2["parameters"]),
        observations,
        load_mechanical_actions(core_db, inst.id),
        date_from=event,
        date_to=event,
    )
    assert v1 and v2
    assert v1[0].sma20_distance is not None and abs(v1[0].sma20_distance) > 0.5
    assert v2[0].sma20_distance is not None and abs(v2[0].sma20_distance) < 0.3


def test_v1_feature_set_stays_active_and_raw(core_db: Session) -> None:
    seed_feature_sets(core_db)
    v1 = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "technical_daily", FeatureSet.version == 1))
    v2 = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "technical_daily", FeatureSet.version == 2))
    assert v1 is not None and v2 is not None
    assert v1.is_active is True
    assert v2.is_active is False
    assert v1.parameters.get("price_basis") != "mechanical_adjusted"
    assert v2.parameters.get("price_basis") == "mechanical_adjusted"
    assert v2.parameters.get("basic_feature_set_version") == 2


def test_rules_v2_is_same_formula_new_identity() -> None:
    from uuid import UUID

    from app.domain.ports.technical import TechnicalFeatureVector, TechnicalModelInput, TechnicalQualityContext

    v1 = RuleBasedTechnicalModel()
    v2 = RuleBasedTechnicalModel(RULES_V2_CONFIG, model_version=RULES_V2_VERSION)
    assert v2.model_code == RULES_V1_CODE
    assert v2.model_version == 2
    frozen = TechnicalModelInput(
        instrument_id=1,
        ticker="X",
        as_of_date=date(2024, 1, 2),
        basic_feature_set_ref=feature_set_ref(UUID(int=2), "basic_daily", 2),
        technical_feature_set_ref=feature_set_ref(UUID(int=3), "technical_daily", 2),
        features=TechnicalFeatureVector(
            sma20_distance=0.01,
            ema20_distance=0.01,
            return_5d=0.01,
            return_20d=0.01,
            rsi14=50.0,
            volume_zscore_20d=0.0,
        ),
        quality=TechnicalQualityContext(),
    )
    out1 = v1.predict(frozen)
    out2 = v2.predict(frozen)
    assert out2.model_version == 2
    assert out1.score == out2.score
    assert out1.direction == out2.direction


def test_signal_service_model_does_not_query_db() -> None:
    model = RuleBasedTechnicalModel(RULES_V2_CONFIG, model_version=2)
    service = TechnicalSignalService(model)
    basic = InstrumentFeatureDaily(
        instrument_id=1,
        date=date(2024, 6, 10),
        timeframe="1d",
        feature_set_id=__import__("uuid").UUID(int=2),
        feature_version=2,
        return_5d=Decimal("0.01"),
        return_20d=Decimal("0.02"),
        volume_zscore_20d=Decimal("0.5"),
        has_sufficient_history=True,
        is_valid=True,
        quality_flags={},
    )
    technical = InstrumentTechnicalFeatureDaily(
        instrument_id=1,
        date=date(2024, 6, 10),
        timeframe="1d",
        feature_set_id=__import__("uuid").UUID(int=3),
        sma20_distance=Decimal("0.01"),
        ema20_distance=Decimal("0.01"),
        rsi14=Decimal("55"),
        atr14_pct=Decimal("0.02"),
        has_sufficient_history=True,
        is_valid=True,
        quality_flags={},
    )
    _frozen, output = service.evaluate(
        instrument_id=1,
        ticker="SBER",
        as_of_date=date(2024, 6, 10),
        basic_ref=feature_set_ref(basic.feature_set_id, "basic_daily", 2),
        technical_ref=feature_set_ref(technical.feature_set_id, "technical_daily", 2),
        basic=basic,
        technical=technical,
    )
    assert output.model_version == 2
    assert 0.0 <= output.confidence <= 1.0


def _seed_candle(session: Session, instrument_id: int, day: date, close: float) -> None:
    ts = datetime(day.year, day.month, day.day, tzinfo=UTC)
    existing = session.scalar(select(Candle).where(Candle.instrument_id == instrument_id, Candle.timestamp == ts))
    if existing is not None:
        return
    session.add(
        Candle(
            instrument_id=instrument_id,
            timeframe="1d",
            timestamp=ts,
            open=Decimal(str(close)),
            high=Decimal(str(close)),
            low=Decimal(str(close)),
            close=Decimal(str(close)),
            volume=Decimal("1000"),
            source="MOEX",
        )
    )
    session.flush()


def _seed_ca(session: Session, instrument_id: int, day: date, event_type: str, before: str, after: str) -> None:
    existing = session.scalar(
        select(CorporateAction).where(
            CorporateAction.instrument_id == instrument_id,
            CorporateAction.event_date == day,
            CorporateAction.event_type == event_type,
        )
    )
    if existing is not None:
        return
    session.add(
        CorporateAction(
            instrument_id=instrument_id,
            event_date=day,
            event_type=event_type,
            payload={
                "split_before": before,
                "split_after": after,
                "adjustment_factor": str(Decimal(after) / Decimal(before)),
            },
            source="MOEX",
        )
    )
    session.flush()
