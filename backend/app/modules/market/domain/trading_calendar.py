"""MOEX equity trading-day calendar (research V1).

Uses the Russian production day-off calendar (isdayoff.ru bitmasks) as a
deterministic holiday set. MOEX equities do not trade on public holidays or
weekends in normal regimes; this is **not** a byte-for-byte official MOEX
session calendar dump, so entitlement quality is
``DERIVED_FROM_RU_PRODUCTION_CALENDAR`` (PARTIAL), never silently READY.

Bit semantics (isdayoff.ru): ``0`` working, ``1`` day off, ``2`` reduced day
(still a working day for settlement walks).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

CALENDAR_VERSION = "moex_equity_trading_calendar_v1"
QUALITY_DERIVED_RU = "DERIVED_FROM_RU_PRODUCTION_CALENDAR"
QUALITY_WEEKENDS_ONLY = "WEEKENDS_ONLY_APPROXIMATE"


@dataclass(frozen=True, slots=True)
class TradingDayAnswer:
    day: date
    is_trading_day: bool
    quality: str
    provenance: dict[str, Any]


class RuProductionDayOffCalendar:
    """Year → 365/366-char bitmask (index 0 = Jan 1)."""

    def __init__(self, year_masks: Mapping[int, str]) -> None:
        self._masks = {int(y): str(m) for y, m in year_masks.items()}

    @classmethod
    def from_directory(cls, directory: Path) -> RuProductionDayOffCalendar:
        masks: dict[int, str] = {}
        for path in sorted(directory.glob("isdayoff_ru_*.txt")):
            year = int(path.stem.rsplit("_", 1)[-1])
            masks[year] = path.read_text(encoding="utf-8").strip()
        return cls(masks)

    def covered_years(self) -> tuple[int, ...]:
        return tuple(sorted(self._masks))

    def day_code(self, day: date) -> int | None:
        mask = self._masks.get(day.year)
        if mask is None:
            return None
        idx = (day - date(day.year, 1, 1)).days
        if idx < 0 or idx >= len(mask):
            return None
        ch = mask[idx]
        if ch not in "012":
            return None
        return int(ch)

    def is_day_off(self, day: date) -> bool | None:
        code = self.day_code(day)
        if code is None:
            return None
        return code == 1


@dataclass
class MoexEquityTradingCalendar:
    """Trading-day predicate for MOEX equities settlement / entitlement walks."""

    day_off: RuProductionDayOffCalendar | None = None
    version: str = CALENDAR_VERSION

    def coverage(self) -> dict[str, Any]:
        years = () if self.day_off is None else self.day_off.covered_years()
        return {
            "version": self.version,
            "quality": QUALITY_DERIVED_RU if years else QUALITY_WEEKENDS_ONLY,
            "years": list(years),
            "earliest": None if not years else f"{years[0]}-01-01",
            "latest": None if not years else f"{years[-1]}-12-31",
            "source": "isdayoff.ru (RU production calendar bitmasks)",
            "note": (
                "Not an official MOEX session calendar export; "
                "weekends + RU public holidays treated as non-trading."
            ),
        }

    def is_trading_day(self, day: date) -> bool:
        if day.weekday() >= 5:
            return False
        if self.day_off is None:
            return True
        off = self.day_off.is_day_off(day)
        if off is None:
            # Outside bundled years: weekends-only fallback for that day.
            return True
        return not off

    def classify(self, day: date) -> TradingDayAnswer:
        trading = self.is_trading_day(day)
        if self.day_off is not None and self.day_off.day_code(day) is not None:
            quality = QUALITY_DERIVED_RU
        else:
            quality = QUALITY_WEEKENDS_ONLY
        return TradingDayAnswer(
            day=day,
            is_trading_day=trading,
            quality=quality,
            provenance={
                "calendar_version": self.version,
                "weekday": day.weekday(),
                "day_off_code": None if self.day_off is None else self.day_off.day_code(day),
            },
        )

    def next_trading_day(self, day: date, *, inclusive: bool = False) -> date | None:
        cursor = day if inclusive else day + timedelta(days=1)
        for _ in range(366 * 3):
            if self.is_trading_day(cursor):
                return cursor
            cursor += timedelta(days=1)
        return None

    def previous_trading_day(self, day: date, *, inclusive: bool = False) -> date | None:
        cursor = day if inclusive else day - timedelta(days=1)
        for _ in range(366 * 3):
            if self.is_trading_day(cursor):
                return cursor
            cursor -= timedelta(days=1)
        return None

    def as_predicate(self):
        return self.is_trading_day
