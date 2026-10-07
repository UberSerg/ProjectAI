"""Idempotent 60m candle upsert into market.candles (DB)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.domain.ports.market_data import CandleBar
from app.infrastructure.market.models import Candle, Instrument
from app.modules.intelligence.intraday.application.persist_candles import upsert_interval_candles
from app.modules.intelligence.intraday.constants import PRIMARY_INTERVAL, SOURCE_MOEX


@pytest.fixture
def equity(core_db) -> Instrument:
    inst = Instrument(
        symbol="TEST60M",
        name="Test 60m",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
    )
    core_db.add(inst)
    core_db.flush()
    return inst


def _bar(ts: datetime, close: str = "100") -> CandleBar:
    c = Decimal(close)
    return CandleBar(
        timestamp=ts,
        open=c,
        high=c + Decimal("1"),
        low=c - Decimal("1"),
        close=c,
        volume=Decimal("1000"),
    )


def test_upsert_interval_candles_idempotent(core_db, equity: Instrument) -> None:
    ts = datetime(2024, 6, 3, 7, 0, tzinfo=UTC)  # 10:00 MSK
    first = upsert_interval_candles(
        core_db,
        int(equity.id),
        [_bar(ts, "100")],
        source=SOURCE_MOEX,
        timeframe=PRIMARY_INTERVAL,
    )
    assert first["received"] == 1
    assert first["inserted"] == 1
    second = upsert_interval_candles(
        core_db,
        int(equity.id),
        [_bar(ts, "101")],
        source=SOURCE_MOEX,
        timeframe=PRIMARY_INTERVAL,
    )
    assert second["updated"] == 1
    assert second["inserted"] == 0
    count = core_db.scalar(
        select(func.count())
        .select_from(Candle)
        .where(
            Candle.instrument_id == equity.id,
            Candle.timeframe == PRIMARY_INTERVAL,
        )
    )
    assert count == 1
    row = core_db.scalar(
        select(Candle).where(
            Candle.instrument_id == equity.id,
            Candle.timeframe == PRIMARY_INTERVAL,
        )
    )
    assert row is not None
    assert row.close == Decimal("101")
    # Must not collide with daily timeframe semantics
    daily = upsert_interval_candles(
        core_db,
        int(equity.id),
        [_bar(datetime(2024, 6, 3, 0, 0, tzinfo=UTC), "100")],
        source=SOURCE_MOEX,
        timeframe="1d",
    )
    assert daily["inserted"] == 1
    assert (
        core_db.scalar(
            select(func.count()).select_from(Candle).where(Candle.instrument_id == equity.id)
        )
        == 2
    )
