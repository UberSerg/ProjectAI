"""Fixed annual cash hurdle — pure post-processing benchmark.

The hurdle answers one question: "would this capital have done better sitting in a
%-per-annum instrument over the same calendar window?". It is computed after the fact
from dates only.

Formula, for a period [t0, t1] and annual rate r:

    calendar_days = (t1 - t0).days
    growth_factor = (1 + r) ** (calendar_days / 365.25)
    hurdle_return = growth_factor - 1

Calendar days (not trading days) are used because interest accrues over the calendar.
365.25 absorbs leap years without a per-year branch.

This module never writes to a portfolio. Simulator and Shadow cash balances are produced
exclusively by fills and corporate actions; adding hurdle interest to them would fabricate
cash that was never received and would corrupt NAV, drawdown and turnover history.
"""

from __future__ import annotations

from datetime import date

from app.modules.model_edge.config import (
    CASH_HURDLE_ANNUAL_RATE,
    CASH_HURDLE_DAY_COUNT,
    CASH_HURDLE_LABEL,
)
from app.modules.model_edge.domain.types import CashHurdle


def cash_hurdle_growth_factor(
    *,
    calendar_days: int,
    annual_rate: float = CASH_HURDLE_ANNUAL_RATE,
    day_count: float = CASH_HURDLE_DAY_COUNT,
) -> float:
    """Compound growth factor for a holding period expressed in calendar days."""
    if calendar_days < 0:
        raise ValueError("calendar_days must not be negative")
    return float((1.0 + annual_rate) ** (calendar_days / day_count))


def compute_cash_hurdle(
    period_from: date,
    period_to: date,
    *,
    annual_rate: float = CASH_HURDLE_ANNUAL_RATE,
    day_count: float = CASH_HURDLE_DAY_COUNT,
    label: str = CASH_HURDLE_LABEL,
) -> CashHurdle:
    if period_to < period_from:
        raise ValueError("period_to must not precede period_from")
    calendar_days = (period_to - period_from).days
    return CashHurdle(
        label=label,
        annual_rate=annual_rate,
        period_from=period_from,
        period_to=period_to,
        calendar_days=calendar_days,
        day_count=day_count,
        growth_factor=cash_hurdle_growth_factor(
            calendar_days=calendar_days, annual_rate=annual_rate, day_count=day_count
        ),
    )


def hurdle_nav(
    initial_capital: float,
    period_from: date,
    period_to: date,
    *,
    annual_rate: float = CASH_HURDLE_ANNUAL_RATE,
) -> float:
    """Notional value of the same capital left in the cash benchmark. Reporting only."""
    hurdle = compute_cash_hurdle(period_from, period_to, annual_rate=annual_rate)
    return float(initial_capital) * hurdle.growth_factor
