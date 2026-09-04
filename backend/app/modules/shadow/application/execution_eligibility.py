"""Forward-causal execution eligibility for Shadow Portfolio V0."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta


def ensure_aware_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def min_execution_market_date(decision_at: datetime) -> date:
    """Safe causal rule: execution_market_date > calendar date of decision_at (UTC).

    Prevents filling on any market date that could already have been known
    on the calendar day the decision/order was created.
    """
    d = ensure_aware_utc(decision_at).date()
    return d + timedelta(days=1)


def is_execution_date_eligible(*, decision_at: datetime, market_date: date) -> bool:
    return market_date >= min_execution_market_date(decision_at)


def iso_week_key(as_of: date) -> str:
    iso = as_of.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
