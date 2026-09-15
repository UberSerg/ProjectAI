"""MOEX equity ex-date estimation from record (registry) date.

PARTIAL quality helper. Settlement cycle (research / ADR 0014):

- T+2 before 2023-07-31
- T+1 on and after 2023-07-31

Ex-date is the first trading day on which a purchase does **not** entitle the
buyer to the dividend for that record date: ``record_date`` minus ``N``
settlement trading days.

Without a trading calendar, weekends-only subtraction is used and provenance
marks ``APPROXIMATE``. Prefer leaving ``ex_date`` null in production ingest
when calendar coverage is missing unless a caller explicitly requests this
estimate.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

# MOEX equity settlement T+2 → T+1 effective date (inclusive of T+1).
MOEX_EQUITY_T1_EFFECTIVE = date(2023, 7, 31)
SETTLEMENT_RULE_VERSION = "moex_equity_settlement_ex_date_v1"


@dataclass(frozen=True, slots=True)
class ExDateEstimate:
    """Result of ``estimate_ex_date`` with honest provenance."""

    ex_date: date | None
    provenance: dict[str, Any]

    @property
    def quality(self) -> str:
        return str(self.provenance.get("quality") or "UNKNOWN")


TradingCalendar = Callable[[date], bool] | Collection[date]


def settlement_lag_trading_days(as_of: date) -> int:
    """Return N for T+N settlement in force on ``as_of``."""
    if as_of >= MOEX_EQUITY_T1_EFFECTIVE:
        return 1
    return 2


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def _is_trading_day(d: date, calendar: TradingCalendar | None) -> bool:
    if calendar is None:
        return not _is_weekend(d)
    if callable(calendar):
        return bool(calendar(d))
    return d in calendar


def _subtract_trading_days(
    start: date,
    n: int,
    *,
    calendar: TradingCalendar | None,
) -> date | None:
    if n < 0:
        return None
    if n == 0:
        return start
    cursor = start
    remaining = n
    # Hard cap avoids infinite loops on pathological calendars.
    for _ in range(366 * 3):
        cursor -= timedelta(days=1)
        if _is_trading_day(cursor, calendar):
            remaining -= 1
            if remaining == 0:
                return cursor
    return None


def estimate_ex_date(
    record_date: date | None,
    *,
    calendar: TradingCalendar | None = None,
) -> tuple[date | None, dict[str, Any]]:
    """Estimate ex-date from record date under MOEX equity settlement rules.

    Returns ``(ex_date|None, provenance)``. Quality is ``PARTIAL`` when a
    calendar is supplied; ``APPROXIMATE`` when only weekends are excluded.
    """
    if record_date is None:
        prov = {
            "rule_version": SETTLEMENT_RULE_VERSION,
            "quality": "UNKNOWN",
            "reason": "missing_record_date",
        }
        return None, prov

    lag = settlement_lag_trading_days(record_date)
    cycle = "T+1" if lag == 1 else "T+2"
    approx = calendar is None
    ex = _subtract_trading_days(record_date, lag, calendar=calendar)
    provenance: dict[str, Any] = {
        "rule_version": SETTLEMENT_RULE_VERSION,
        "settlement_cycle": cycle,
        "settlement_lag_trading_days": lag,
        "t1_effective_from": MOEX_EQUITY_T1_EFFECTIVE.isoformat(),
        "record_date": record_date.isoformat(),
        "calendar": "provided" if calendar is not None else "weekends_only",
        "quality": "APPROXIMATE" if approx else "PARTIAL",
        "note": (
            "Meeting/registry dates are not disclosure timestamps; this helper "
            "only derives economic ex-date relative to record_date."
        ),
    }
    if ex is None:
        provenance["reason"] = "calendar_walk_exhausted"
    else:
        provenance["ex_date"] = ex.isoformat()
    return ex, provenance
