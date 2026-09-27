"""Detect local EOD lag vs expected completed MOEX equity session.

Root cause of false ALREADY_CURRENT after downtime: autonomy/catch-up used only
local complete candle dates. When market+shadow watermarks matched locally,
Kraken never probed the provider / trading calendar for newer completed sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, InstrumentSource
from app.modules.market.infrastructure.ru_trading_calendar import get_moex_equity_trading_calendar
from app.modules.prediction.application.forward_readiness import (
    latest_raw_market_date,
    select_latest_complete_as_of,
)

MSK = ZoneInfo("Europe/Moscow")
# MOEX equities EOD is treated complete after evening settlement window (MSK).
EOD_COMPLETE_AFTER_MSK = time(19, 0)

MARKET_CURRENT = "MARKET_CURRENT"
MARKET_STALE = "MARKET_STALE"
MARKET_UNKNOWN = "MARKET_UNKNOWN"


@dataclass(frozen=True, slots=True)
class MarketEodGap:
    local_raw_max: date | None
    local_complete_eod: date | None
    expected_completed_session: date | None
    missing_trading_sessions: list[date] = field(default_factory=list)
    missing_count: int = 0
    status: str = MARKET_UNKNOWN
    calendar_quality: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_raw_max": self.local_raw_max.isoformat() if self.local_raw_max else None,
            "local_complete_eod": (
                self.local_complete_eod.isoformat() if self.local_complete_eod else None
            ),
            "expected_completed_session": (
                self.expected_completed_session.isoformat()
                if self.expected_completed_session
                else None
            ),
            "missing_trading_sessions": [d.isoformat() for d in self.missing_trading_sessions],
            "missing_count": self.missing_count,
            "status": self.status,
            "calendar_quality": self.calendar_quality,
            "reason": self.reason,
            "market_current": self.status == MARKET_CURRENT,
        }


def expected_completed_equity_session(
    *,
    now: datetime | None = None,
    calendar=None,
) -> date | None:
    """Latest MOEX equity session that should already have EOD candles available."""
    cal = calendar or get_moex_equity_trading_calendar()
    now_utc = now or datetime.now(UTC)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    now_msk = now_utc.astimezone(MSK)
    today = now_msk.date()

    if cal.is_trading_day(today) and now_msk.time() >= EOD_COMPLETE_AFTER_MSK:
        return today
    return cal.previous_trading_day(today, inclusive=False)


def trading_sessions_between(
    start_exclusive: date | None,
    end_inclusive: date | None,
    *,
    calendar=None,
) -> list[date]:
    """Trading sessions strictly after start_exclusive through end_inclusive."""
    if end_inclusive is None:
        return []
    cal = calendar or get_moex_equity_trading_calendar()
    cursor = (start_exclusive + timedelta(days=1)) if start_exclusive is not None else end_inclusive
    if start_exclusive is None:
        # Without a local anchor, only report the expected session itself.
        return [end_inclusive] if cal.is_trading_day(end_inclusive) else []
    out: list[date] = []
    day = cursor
    guard = 0
    while day <= end_inclusive and guard < 800:
        if cal.is_trading_day(day):
            out.append(day)
        day += timedelta(days=1)
        guard += 1
    return out


def instruments_with_moex_history(session: Session) -> list[Instrument]:
    """Instruments that participate in incremental EOD (proven MOEX mapping)."""
    ids = session.scalars(
        select(InstrumentSource.instrument_id)
        .where(
            InstrumentSource.source == "MOEX",
            InstrumentSource.valid_from.is_not(None),
        )
        .distinct()
    ).all()
    if not ids:
        return []
    return list(
        session.scalars(
            select(Instrument)
            .where(Instrument.id.in_(list(ids)), Instrument.is_active.is_(True))
            .order_by(Instrument.symbol)
        ).all()
    )


def detect_market_eod_gap(
    session: Session,
    *,
    now: datetime | None = None,
    calendar=None,
) -> MarketEodGap:
    cal = calendar or get_moex_equity_trading_calendar()
    coverage = cal.coverage()
    expected = expected_completed_equity_session(now=now, calendar=cal)
    raw_max = latest_raw_market_date(session)
    complete = select_latest_complete_as_of(session)
    local_complete = complete.as_of if complete.complete else complete.as_of

    if expected is None:
        return MarketEodGap(
            local_raw_max=raw_max,
            local_complete_eod=local_complete,
            expected_completed_session=None,
            status=MARKET_UNKNOWN,
            calendar_quality=coverage.get("quality"),
            reason="no_expected_session",
        )

    anchor = local_complete or raw_max
    missing = trading_sessions_between(anchor, expected, calendar=cal)
    # If raw max already reached expected but completeness lags, still stale for ops.
    if not missing and raw_max is not None and raw_max >= expected and local_complete is not None:
        if local_complete >= expected:
            return MarketEodGap(
                local_raw_max=raw_max,
                local_complete_eod=local_complete,
                expected_completed_session=expected,
                missing_trading_sessions=[],
                missing_count=0,
                status=MARKET_CURRENT,
                calendar_quality=coverage.get("quality"),
                reason="local_eod_current",
            )

    if not missing and (anchor is None or anchor < expected):
        missing = trading_sessions_between(anchor, expected, calendar=cal)

    if missing:
        return MarketEodGap(
            local_raw_max=raw_max,
            local_complete_eod=local_complete,
            expected_completed_session=expected,
            missing_trading_sessions=missing,
            missing_count=len(missing),
            status=MARKET_STALE,
            calendar_quality=coverage.get("quality"),
            reason="local_eod_behind_expected_session",
        )

    # Completeness incomplete at expected even if calendar gap empty
    if local_complete is None or local_complete < expected:
        return MarketEodGap(
            local_raw_max=raw_max,
            local_complete_eod=local_complete,
            expected_completed_session=expected,
            missing_trading_sessions=trading_sessions_between(local_complete, expected, calendar=cal),
            missing_count=0,
            status=MARKET_STALE,
            calendar_quality=coverage.get("quality"),
            reason="completeness_behind_expected",
        )

    return MarketEodGap(
        local_raw_max=raw_max,
        local_complete_eod=local_complete,
        expected_completed_session=expected,
        missing_trading_sessions=[],
        missing_count=0,
        status=MARKET_CURRENT,
        calendar_quality=coverage.get("quality"),
        reason="local_eod_current",
    )


def candle_dates_in_range(
    session: Session, *, date_from: date, date_to: date
) -> list[date]:
    rows = session.scalars(
        select(func.date(Candle.timestamp))
        .where(
            Candle.timeframe == "1d",
            func.date(Candle.timestamp) >= date_from,
            func.date(Candle.timestamp) <= date_to,
        )
        .distinct()
        .order_by(func.date(Candle.timestamp))
    ).all()
    out: list[date] = []
    for r in rows:
        if isinstance(r, date):
            out.append(r)
        else:
            out.append(date.fromisoformat(str(r)))
    return out


__all__ = [
    "MARKET_CURRENT",
    "MARKET_STALE",
    "MARKET_UNKNOWN",
    "MarketEodGap",
    "candle_dates_in_range",
    "detect_market_eod_gap",
    "expected_completed_equity_session",
    "instruments_with_moex_history",
    "trading_sessions_between",
]
