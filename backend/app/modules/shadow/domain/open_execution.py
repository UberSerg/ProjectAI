"""SHADOW_NEXT_SESSION_OPEN_V1 — pure eligibility helpers (no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from app.domain.ports.intraday_market import MarketSessionStatus, QuoteFreshness

POLICY_NAME = "SHADOW_NEXT_SESSION_OPEN_V1"
EXECUTION_PRICE_TYPE = "OFFICIAL_SESSION_OPEN"
QUOTE_SOURCE = "MOEX_ISS"

# MOEX equities main session open ≈ 10:00 MSK = 07:00 UTC.
MOEX_SESSION_OPEN_UTC = time(7, 0)

REASON_ELIGIBLE = "ELIGIBLE"
REASON_NEXT_SESSION_NOT_STARTED = "NEXT_SESSION_NOT_STARTED"
REASON_WAITING_NEXT_SESSION = "WAITING_NEXT_SESSION"
REASON_OPEN_PRICE_NOT_AVAILABLE = "OPEN_PRICE_NOT_AVAILABLE"
REASON_ORDER_CREATED_AFTER_OPEN = "ORDER_CREATED_AFTER_OPEN"
REASON_QUOTE_STALE = "QUOTE_STALE"
REASON_QUOTE_UNAVAILABLE = "QUOTE_UNAVAILABLE"
REASON_MARKET_CLOSED = "MARKET_CLOSED"
REASON_NON_TRADING_DAY = "NON_TRADING_DAY"
REASON_NO_TRADES = "NO_TRADES"
REASON_MIN_EXECUTION_DATE = "MIN_EXECUTION_DATE_NOT_REACHED"


@dataclass(slots=True, frozen=True)
class OpenFillEligibility:
    eligible: bool
    reason: str
    delayed_observation: bool = False
    session_open_time: datetime | None = None


def ensure_aware_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def session_open_time_utc(session_date: date) -> datetime:
    """Canonical V1 session-open instant used when exchange open clock is unknown."""
    return datetime.combine(session_date, MOEX_SESSION_OPEN_UTC, tzinfo=UTC)


def can_fill_with_session_open(
    *,
    order_created_at: datetime,
    min_execution_date: date,
    session_date: date,
    open_price: float | None,
    market_status: MarketSessionStatus | str,
    quote_freshness: QuoteFreshness | str,
    observed_at: datetime,
    now: datetime | None = None,
) -> OpenFillEligibility:
    """Decide whether a PENDING shadow order may fill at official session OPEN.

    Late observation is allowed only when the order existed before session open:
    filled_at should be set to observed_at and delayed_observation=True.

    V1 safety for same-day orders: if order_created_at falls on session_date at or
    after 07:00 UTC (10:00 MSK), treat as ORDER_CREATED_AFTER_OPEN (cannot prove
    the order existed before the open auction).
    """
    created = ensure_aware_utc(order_created_at)
    observed = ensure_aware_utc(observed_at)
    clock = ensure_aware_utc(now) if now is not None else observed
    open_at = session_open_time_utc(session_date)
    status = MarketSessionStatus(str(market_status))
    freshness = QuoteFreshness(str(quote_freshness))

    if session_date < min_execution_date:
        return OpenFillEligibility(
            False, REASON_MIN_EXECUTION_DATE, session_open_time=open_at
        )

    if status is MarketSessionStatus.NON_TRADING_DAY:
        return OpenFillEligibility(
            False, REASON_NON_TRADING_DAY, session_open_time=open_at
        )

    if freshness is QuoteFreshness.UNAVAILABLE:
        return OpenFillEligibility(
            False, REASON_QUOTE_UNAVAILABLE, session_open_time=open_at
        )

    if freshness is QuoteFreshness.STALE:
        return OpenFillEligibility(False, REASON_QUOTE_STALE, session_open_time=open_at)

    if freshness is QuoteFreshness.SESSION_NOT_STARTED or status is MarketSessionStatus.PREOPEN:
        return OpenFillEligibility(
            False, REASON_NEXT_SESSION_NOT_STARTED, session_open_time=open_at
        )

    if freshness is QuoteFreshness.NO_TRADES:
        return OpenFillEligibility(False, REASON_NO_TRADES, session_open_time=open_at)

    if status is MarketSessionStatus.CLOSED and open_price is None:
        return OpenFillEligibility(
            False, REASON_MARKET_CLOSED, session_open_time=open_at
        )

    if open_price is None or float(open_price) <= 0:
        # Session may be open but OPEN not published yet.
        if clock < open_at:
            return OpenFillEligibility(
                False, REASON_NEXT_SESSION_NOT_STARTED, session_open_time=open_at
            )
        return OpenFillEligibility(
            False, REASON_OPEN_PRICE_NOT_AVAILABLE, session_open_time=open_at
        )

    # Order must have existed before session open.
    if created >= open_at:
        # Same calendar session after open → reject; earlier sessions already
        # constrained by min_execution_date.
        return OpenFillEligibility(
            False, REASON_ORDER_CREATED_AFTER_OPEN, session_open_time=open_at
        )

    # If we somehow have an open for a session before the order's calendar day
    # and open, wait for a later session (should be rare with min_execution_date).
    if created.date() > session_date:
        return OpenFillEligibility(
            False, REASON_WAITING_NEXT_SESSION, session_open_time=open_at
        )

    delayed = observed > open_at
    return OpenFillEligibility(
        True,
        REASON_ELIGIBLE,
        delayed_observation=delayed,
        session_open_time=open_at,
    )
