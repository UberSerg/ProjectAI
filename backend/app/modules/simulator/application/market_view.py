"""Market price / corporate-action views for Simulator V0."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, Series, SeriesValue
from app.modules.investment.domain.hurdle import HurdleQuote, KnownAtQuality
from app.modules.market.application.mechanical_adjustment import (
    MechanicalAction,
    load_mechanical_actions,
)


@dataclass(frozen=True, slots=True)
class DayBar:
    open: float
    close: float


class MarketView:
    """In-memory RAW candle + mechanical CA lookup for simulation period."""

    def __init__(
        self,
        *,
        bars: dict[int, dict[date, DayBar]],
        actions: dict[int, list[MechanicalAction]],
        tickers: dict[int, str],
        trading_days: list[date],
        imoex_id: int | None,
        cbr_hurdle_quotes: tuple[HurdleQuote, ...] = (),
    ) -> None:
        self.bars = bars
        self.actions = actions
        self.tickers = tickers
        self.trading_days = trading_days
        self.imoex_id = imoex_id
        self.cbr_hurdle_quotes = cbr_hurdle_quotes

    def open_price(self, instrument_id: int, d: date) -> float | None:
        bar = self.bars.get(instrument_id, {}).get(d)
        return None if bar is None else bar.open

    def close_price(self, instrument_id: int, d: date) -> float | None:
        bar = self.bars.get(instrument_id, {}).get(d)
        return None if bar is None else bar.close

    def ca_on(self, instrument_id: int, d: date) -> list[MechanicalAction]:
        return [a for a in self.actions.get(instrument_id, []) if a.event_date == d]

    def imoex_close(self, d: date) -> float | None:
        if self.imoex_id is None:
            return None
        return self.close_price(self.imoex_id, d)


def load_market_view(
    session: Session,
    *,
    instrument_ids: set[int],
    date_from: date,
    date_to: date,
) -> MarketView:
    """Load RAW 1d OHLCV opens/closes and mechanical actions. Does not adjust candles."""
    ids = set(instrument_ids)
    imoex = session.scalar(select(Instrument).where(Instrument.symbol == "IMOEX"))
    if imoex is not None:
        ids.add(imoex.id)

    instruments = list(
        session.scalars(select(Instrument).where(Instrument.id.in_(sorted(ids))))
    )
    tickers = {i.id: i.symbol for i in instruments}

    start_dt = datetime.combine(date_from, time.min, tzinfo=UTC)
    end_dt = datetime.combine(date_to, time.max, tzinfo=UTC)
    candles = list(
        session.scalars(
            select(Candle).where(
                Candle.instrument_id.in_(sorted(ids)),
                Candle.timeframe == "1d",
                Candle.timestamp >= start_dt,
                Candle.timestamp <= end_dt,
            )
        )
    )
    bars: dict[int, dict[date, DayBar]] = defaultdict(dict)
    day_set: set[date] = set()
    for c in candles:
        d = c.timestamp.date() if hasattr(c.timestamp, "date") else c.timestamp
        if not isinstance(d, date):
            d = date.fromisoformat(str(d)[:10])
        if c.open is None or c.close is None:
            continue
        bars[int(c.instrument_id)][d] = DayBar(open=float(c.open), close=float(c.close))
        # Trading calendar from equity cohort only (exclude pure index days if desired)
        if imoex is None or int(c.instrument_id) != imoex.id:
            day_set.add(d)

    # If all instruments are index-only, fall back to any days present
    if not day_set:
        for by_day in bars.values():
            day_set.update(by_day.keys())

    actions: dict[int, list[MechanicalAction]] = {}
    for iid in ids:
        if imoex is not None and iid == imoex.id:
            continue
        actions[iid] = load_mechanical_actions(session, iid)

    key_rate_rows = session.execute(
        select(SeriesValue, Series)
        .join(Series, Series.id == SeriesValue.series_id)
        .where(
            Series.code == "KEY_RATE",
            SeriesValue.timestamp <= end_dt,
        )
        .order_by(SeriesValue.timestamp)
    ).all()
    hurdle_quotes = tuple(
        HurdleQuote(
            as_of=value.timestamp.date(),
            annual_rate=float(value.value) / 100,
            known_at=value.timestamp.date(),
            known_at_quality=KnownAtQuality.DATE_ONLY,
            source=series.source,
        )
        for value, series in key_rate_rows
    )

    return MarketView(
        bars=dict(bars),
        actions=actions,
        tickers=tickers,
        trading_days=sorted(day_set),
        imoex_id=imoex.id if imoex is not None else None,
        cbr_hurdle_quotes=hurdle_quotes,
    )


def quantity_after_ca(quantity: float, factor: Decimal) -> float:
    """Share quantity scales with mechanical factor (same basis as volume)."""
    return float(Decimal(str(quantity)) * factor)
