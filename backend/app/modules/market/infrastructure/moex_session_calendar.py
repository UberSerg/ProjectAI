"""MOEX equity trading sessions derived from official ISS history.

Primary source: bundled TRADEDATE set from MOEX ISS history for SBER TQBR
(observed equity trading sessions). Secondary: MOEX engine ``dailytable``
non-work exceptions for documentation/cross-check.

This is **not** the Russian production (isdayoff) workday calendar.
Quality: ``DERIVED_FROM_MOEX_ISS_HISTORY_SESSIONS``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

CALENDAR_VERSION = "moex_equity_session_calendar_v1"
QUALITY_MOEX_HISTORY = "DERIVED_FROM_MOEX_ISS_HISTORY_SESSIONS"
QUALITY_WEEKENDS_ONLY = "WEEKENDS_ONLY_APPROXIMATE"

_DATA_DIR = Path(__file__).resolve().parent / "calendar_data"
_SESSIONS_FILE = "moex_sber_tqbr_trading_days_2021_2026.txt"


@dataclass
class MoexIssHistorySessionCalendar:
    """Trading-day set built from MOEX ISS equity history TRADEDATE values."""

    trading_days: set[date] = field(default_factory=set)
    version: str = CALENDAR_VERSION
    source_secid: str = "SBER"
    source_board: str = "TQBR"

    @classmethod
    def from_file(cls, path: Path) -> MoexIssHistorySessionCalendar:
        days: set[date] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            days.add(date.fromisoformat(text[:10]))
        return cls(trading_days=days)

    def coverage(self) -> dict[str, Any]:
        if not self.trading_days:
            return {
                "version": self.version,
                "quality": QUALITY_WEEKENDS_ONLY,
                "days": 0,
                "source": "empty",
            }
        ordered = sorted(self.trading_days)
        return {
            "version": self.version,
            "quality": QUALITY_MOEX_HISTORY,
            "days": len(ordered),
            "earliest": ordered[0].isoformat(),
            "latest": ordered[-1].isoformat(),
            "source": (
                f"MOEX ISS history engines/stock/markets/shares/boards/"
                f"{self.source_board}/securities/{self.source_secid} TRADEDATE"
            ),
            "note": (
                "Observed equity trading sessions for a liquid TQBR name; "
                "used as MOEX equity session proxy for entitlement walks. "
                "Engine dailytable alone only lists exceptions (~tens of rows)."
            ),
        }

    def is_trading_day(self, day: date) -> bool:
        if self.trading_days:
            if day < min(self.trading_days) or day > max(self.trading_days):
                # Outside bundled window: weekdays-only approximate.
                return day.weekday() < 5
            return day in self.trading_days
        return day.weekday() < 5

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

    def shift_trading_days(self, day: date, n: int) -> date | None:
        if n == 0:
            return day if self.is_trading_day(day) else self.previous_trading_day(day)
        cursor = day
        step = 1 if n > 0 else -1
        remaining = abs(n)
        for _ in range(366 * 3):
            cursor = cursor + timedelta(days=step)
            if self.is_trading_day(cursor):
                remaining -= 1
                if remaining == 0:
                    return cursor
        return None

    def as_predicate(self):
        return self.is_trading_day


@lru_cache(maxsize=1)
def get_moex_iss_history_session_calendar() -> MoexIssHistorySessionCalendar:
    path = _DATA_DIR / _SESSIONS_FILE
    if path.is_file():
        return MoexIssHistorySessionCalendar.from_file(path)
    return MoexIssHistorySessionCalendar(trading_days=set())
