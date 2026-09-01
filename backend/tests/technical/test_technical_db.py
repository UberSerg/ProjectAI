"""DB integration: technical feature/signal persistence (transactional fixture, no commit)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import FeatureSet, InstrumentFeatureDaily
from app.infrastructure.market.models import Candle, Instrument
from app.infrastructure.ml.technical_rules import RuleBasedTechnicalModel
from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily, TechnicalSignalDaily
from app.infrastructure.technical.repository import upsert_technical_features, upsert_technical_signals
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.technical.application.calculator import OhlcObservation, TechnicalFeatureCalculator
from app.modules.technical.application.signal_service import TechnicalSignalService, feature_set_ref
from app.modules.technical.technical_config import RULES_V1_CODE, RULES_V1_CONFIG_HASH, RULES_V1_VERSION


@pytest.fixture
def tech_instrument(core_db: Session) -> Instrument:
    seed_feature_sets(core_db)
    existing = core_db.scalar(select(Instrument).where(Instrument.symbol == "TECHTEST"))
    if existing:
        return existing
    inst = Instrument(
        symbol="TECHTEST",
        name="Tech Test",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
    )
    core_db.add(inst)
    core_db.flush()
    start = date(2024, 1, 2)
    for i in range(40):
        c = 100.0 + i * 0.5
        core_db.add(
            Candle(
                instrument_id=inst.id,
                timestamp=datetime(start.year, start.month, start.day, tzinfo=UTC) + timedelta(days=i),
                timeframe="1d",
                open=Decimal(str(c)),
                high=Decimal(str(c + 1)),
                low=Decimal(str(c - 1)),
                close=Decimal(str(c)),
                volume=Decimal("1000"),
                source="test",
                ingested_at=datetime.now(UTC),
            )
        )
    basic = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "basic_daily", FeatureSet.version == 1))
    assert basic is not None
    for i in range(40):
        d = start + timedelta(days=i)
        core_db.add(
            InstrumentFeatureDaily(
                instrument_id=inst.id,
                date=d,
                timeframe="1d",
                feature_set_id=basic.id,
                feature_version=1,
                close=Decimal(str(100 + i * 0.5)),
                return_5d=Decimal("0.02"),
                return_20d=Decimal("0.05"),
                volume_zscore_20d=Decimal("1.0"),
                has_sufficient_history=True,
                is_valid=True,
                quality_flags={},
            )
        )
    core_db.flush()
    return inst


def test_upsert_technical_features_idempotent(core_db: Session, tech_instrument: Instrument) -> None:
    seed_feature_sets(core_db)
    tech_fs = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "technical_daily", FeatureSet.version == 1))
    assert tech_fs is not None
    candles = list(
        core_db.scalars(select(Candle).where(Candle.instrument_id == tech_instrument.id).order_by(Candle.timestamp))
    )
    obs = [
        OhlcObservation(
            date=c.timestamp.date(),
            open=float(c.open),
            high=float(c.high),
            low=float(c.low),
            close=float(c.close),
        )
        for c in candles
    ]
    records = TechnicalFeatureCalculator().calculate(obs, date_from=date(2024, 1, 20))
    n1 = upsert_technical_features(
        core_db, instrument_id=tech_instrument.id, feature_set_id=tech_fs.id, records=records
    )
    core_db.flush()
    n2 = upsert_technical_features(
        core_db, instrument_id=tech_instrument.id, feature_set_id=tech_fs.id, records=records
    )
    core_db.flush()
    assert n1 == n2
    count = core_db.scalar(
        select(func.count())
        .select_from(InstrumentTechnicalFeatureDaily)
        .where(InstrumentTechnicalFeatureDaily.instrument_id == tech_instrument.id)
    )
    assert count == n1


def test_signal_upsert_idempotent(core_db: Session, tech_instrument: Instrument) -> None:
    seed_feature_sets(core_db)
    basic = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "basic_daily", FeatureSet.version == 1))
    tech = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "technical_daily", FeatureSet.version == 1))
    assert basic and tech
    row = {
        "instrument_id": tech_instrument.id,
        "as_of_date": date(2024, 1, 25),
        "timeframe": "1d",
        "run_id": None,
        "model_code": RULES_V1_CODE,
        "model_version": RULES_V1_VERSION,
        "model_config_hash": RULES_V1_CONFIG_HASH,
        "basic_feature_set_id": basic.id,
        "technical_feature_set_id": tech.id,
        "source_basic_feature_id": None,
        "source_technical_feature_id": None,
        "score": Decimal("0.5"),
        "confidence": Decimal("0.8"),
        "direction": "bullish",
        "trend_contribution": Decimal("0.4"),
        "momentum_contribution": Decimal("0.5"),
        "rsi_contribution": Decimal("0.3"),
        "volume_contribution": Decimal("0.1"),
        "is_valid": True,
        "quality_flags": {},
        "calculated_at": datetime.now(UTC),
    }
    assert upsert_technical_signals(core_db, rows=[row]) == 1
    core_db.flush()
    assert upsert_technical_signals(core_db, rows=[row]) == 1
    core_db.flush()
    count = core_db.scalar(
        select(func.count())
        .select_from(TechnicalSignalDaily)
        .where(TechnicalSignalDaily.instrument_id == tech_instrument.id)
    )
    assert count == 1


def test_signal_service_builds_frozen_input(core_db: Session, tech_instrument: Instrument) -> None:
    seed_feature_sets(core_db)
    basic = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "basic_daily", FeatureSet.version == 1))
    tech = core_db.scalar(select(FeatureSet).where(FeatureSet.code == "technical_daily", FeatureSet.version == 1))
    assert basic and tech
    d = date(2024, 1, 25)
    basic_row = core_db.scalar(
        select(InstrumentFeatureDaily).where(
            InstrumentFeatureDaily.instrument_id == tech_instrument.id,
            InstrumentFeatureDaily.date == d,
        )
    )
    candles = list(
        core_db.scalars(select(Candle).where(Candle.instrument_id == tech_instrument.id).order_by(Candle.timestamp))
    )
    obs = [
        OhlcObservation(
            date=c.timestamp.date(),
            open=float(c.open),
            high=float(c.high),
            low=float(c.low),
            close=float(c.close),
        )
        for c in candles
    ]
    upsert_technical_features(
        core_db,
        instrument_id=tech_instrument.id,
        feature_set_id=tech.id,
        records=TechnicalFeatureCalculator().calculate(obs, date_from=d, date_to=d),
    )
    core_db.flush()
    tech_row = core_db.scalar(
        select(InstrumentTechnicalFeatureDaily).where(
            InstrumentTechnicalFeatureDaily.instrument_id == tech_instrument.id,
            InstrumentTechnicalFeatureDaily.date == d,
        )
    )
    assert basic_row and tech_row
    svc = TechnicalSignalService(RuleBasedTechnicalModel())
    frozen, out = svc.evaluate(
        instrument_id=tech_instrument.id,
        ticker="TECHTEST",
        as_of_date=d,
        basic_ref=feature_set_ref(basic.id, basic.code, basic.version),
        technical_ref=feature_set_ref(tech.id, tech.code, tech.version),
        basic=basic_row,
        technical=tech_row,
    )
    assert frozen.as_of_date == d
    if tech_row.rsi14 is not None:
        assert frozen.features.rsi14 == float(tech_row.rsi14)
    else:
        assert frozen.features.rsi14 is None
    assert out.model_code == "rules"
