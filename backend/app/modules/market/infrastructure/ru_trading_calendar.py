"""Load bundled RU production day-off calendars for MOEX equity trading days."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.modules.market.domain.trading_calendar import (
    MoexEquityTradingCalendar,
    RuProductionDayOffCalendar,
)

_DATA_DIR = Path(__file__).resolve().parent / "calendar_data"


@lru_cache(maxsize=1)
def load_bundled_ru_day_off_calendar() -> RuProductionDayOffCalendar:
    return RuProductionDayOffCalendar.from_directory(_DATA_DIR)


@lru_cache(maxsize=1)
def get_moex_equity_trading_calendar() -> MoexEquityTradingCalendar:
    day_off = load_bundled_ru_day_off_calendar()
    return MoexEquityTradingCalendar(day_off=day_off)
