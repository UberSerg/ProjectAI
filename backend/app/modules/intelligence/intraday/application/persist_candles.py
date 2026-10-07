"""Idempotent upsert of interval candles into market.candles."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.ports.market_data import CandleBar
from app.infrastructure.market.models import Candle
from app.modules.market.application.ingest import deduplicate_records


def _as_decimal(value: Decimal | float | int | None, fallback: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return fallback
    return Decimal(str(value))


def upsert_interval_candles(
    session: Session,
    instrument_id: int,
    records: list[CandleBar] | tuple[CandleBar, ...],
    *,
    source: str,
    timeframe: str,
) -> dict[str, int]:
    """Upsert OHLC bars for an arbitrary timeframe (e.g. 60m). Idempotent on uq_market_candles."""
    rows = []
    for bar in deduplicate_records(list(records)):
        close = _as_decimal(bar.close)
        rows.append(
            {
                "instrument_id": instrument_id,
                "timeframe": timeframe,
                "timestamp": bar.timestamp,
                "open": _as_decimal(bar.open, close),
                "high": _as_decimal(bar.high, close),
                "low": _as_decimal(bar.low, close),
                "close": close,
                "volume": None if bar.volume is None else _as_decimal(bar.volume),
                "source": source,
            }
        )
    if not rows:
        return {"received": 0, "inserted": 0, "updated": 0}
    timestamps = [row["timestamp"] for row in rows]
    existing = (
        session.scalar(
            select(func.count())
            .select_from(Candle)
            .where(
                Candle.instrument_id == instrument_id,
                Candle.timeframe == timeframe,
                Candle.source == source,
                Candle.timestamp.in_(timestamps),
            )
        )
        or 0
    )
    stmt = insert(Candle).values(rows)
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_market_candles",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "ingested_at": func.now(),
            },
        )
    )
    received = len(rows)
    updated = int(existing)
    inserted = max(0, received - updated)
    return {"received": received, "inserted": inserted, "updated": updated}
