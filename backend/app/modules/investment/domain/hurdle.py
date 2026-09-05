"""Экономический порог доходности на основе ключевой ставки ЦБ РФ."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from math import prod
from typing import Protocol


class KnownAtQuality(StrEnum):
    DATE_ONLY = "DATE_ONLY"
    EXACT_TIMESTAMP = "EXACT_TIMESTAMP"


class BenchmarkVerdict(StrEnum):
    BEATS_HURDLE = "BEATS_HURDLE"
    BELOW_HURDLE = "BELOW_HURDLE"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class HurdleQuote:
    as_of: date
    annual_rate: float
    known_at: date | datetime
    known_at_quality: KnownAtQuality
    source: str
    benchmark_type: str = "CBR_KEY_RATE"


class HurdleRateProvider(Protocol):
    def quote(self, as_of: date) -> HurdleQuote | None: ...


TRADING_DAYS = {"1d": 1, "5d": 5, "10d": 10, "20d": 20, "1m": 21, "3m": 63, "1y": 252}


def horizon_return(annual_rate: float, horizon: str) -> float:
    """Convert an effective annual rate to the requested trading horizon."""
    if horizon not in TRADING_DAYS:
        raise ValueError(f"Unsupported horizon: {horizon}")
    if annual_rate <= -1:
        raise ValueError("annual_rate must be greater than -1")
    return (1 + annual_rate) ** (TRADING_DAYS[horizon] / 252) - 1


def piecewise_calendar_accrual(
    start: date, end: date, quotes: Sequence[HurdleQuote]
) -> float:
    """Accrue a historical rate curve by calendar days, respecting known_at."""
    if end < start:
        raise ValueError("end must not precede start")
    eligible = sorted(
        (q for q in quotes if q.as_of <= end and _known_date(q.known_at) <= q.as_of),
        key=lambda q: q.as_of,
    )
    factors: list[float] = []
    for index, quote in enumerate(eligible):
        segment_start = max(start, quote.as_of)
        next_date = eligible[index + 1].as_of if index + 1 < len(eligible) else end
        segment_end = min(end, next_date)
        days = (segment_end - segment_start).days
        if days > 0:
            factors.append((1 + quote.annual_rate) ** (days / 365))
    return prod(factors) - 1 if factors else 0.0


def _known_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


@dataclass(frozen=True)
class BenchmarkMetrics:
    strategy_return: float
    hurdle_return: float
    excess_return: float
    annualized_strategy_return: float | None
    annualized_hurdle_return: float | None
    annualized_excess_return: float | None
    excess_after_costs: float
    hurdle_win_rate: float | None
    verdict: BenchmarkVerdict


def benchmark_metrics(
    *,
    strategy_return: float,
    hurdle_return: float,
    periods: int,
    costs: float = 0.0,
    period_excess: Sequence[float] = (),
) -> BenchmarkMetrics:
    excess = strategy_return - hurdle_return
    annual_factor = 252 / periods if periods > 0 else None
    annual_strategy = (
        (1 + strategy_return) ** annual_factor - 1
        if annual_factor is not None and strategy_return > -1
        else None
    )
    annual_hurdle = (
        (1 + hurdle_return) ** annual_factor - 1
        if annual_factor is not None and hurdle_return > -1
        else None
    )
    annual_excess = (
        annual_strategy - annual_hurdle
        if annual_strategy is not None and annual_hurdle is not None
        else None
    )
    after_costs = excess - costs
    verdict = (
        BenchmarkVerdict.INCONCLUSIVE
        if periods <= 0
        else BenchmarkVerdict.BEATS_HURDLE
        if after_costs > 0
        else BenchmarkVerdict.BELOW_HURDLE
    )
    return BenchmarkMetrics(
        strategy_return=strategy_return,
        hurdle_return=hurdle_return,
        excess_return=excess,
        annualized_strategy_return=annual_strategy,
        annualized_hurdle_return=annual_hurdle,
        annualized_excess_return=annual_excess,
        excess_after_costs=after_costs,
        hurdle_win_rate=(
            sum(value > 0 for value in period_excess) / len(period_excess)
            if period_excess
            else None
        ),
        verdict=verdict,
    )
