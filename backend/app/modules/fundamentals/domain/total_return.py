"""Gross total return foundation (pre-tax, pre-commission).

Pure domain helpers — no DB, no FastAPI, no Dataset mutation.
Distinguishes price_return vs dividend_cash vs total_return_gross.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class ReturnQuality(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    NOT_READY = "NOT_READY"


TOTAL_RETURN_MODE = "TOTAL_RETURN_GROSS_V1"
# Simulator / Shadow: not wired in this foundation PR.
SIMULATOR_TOTAL_RETURN_STATUS = "NOT_IN_THIS_PR"


@dataclass(frozen=True, slots=True)
class DividendCashPoint:
    """Cash dividend economically attributed at ex_date (gross, per share)."""

    ex_date: date
    amount_per_share: float | None
    currency: str | None = None
    known_at: date | None = None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class PeriodReturnBreakdown:
    start_date: date
    end_date: date
    start_price: float | None
    end_price: float | None
    price_return: float | None
    dividend_cash: float | None
    total_return_gross: float | None
    quality: ReturnQuality
    reasons: tuple[str, ...] = ()
    dividends_considered: int = 0
    dividends_with_amount: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "start_price": self.start_price,
            "end_price": self.end_price,
            "price_return": self.price_return,
            "dividend_cash": self.dividend_cash,
            "total_return_gross": self.total_return_gross,
            "quality": self.quality.value,
            "reasons": list(self.reasons),
            "dividends_considered": self.dividends_considered,
            "dividends_with_amount": self.dividends_with_amount,
            "mode": TOTAL_RETURN_MODE,
            "tax_treatment": "gross_pre_tax",
            "commission_treatment": "excluded",
        }


def compute_price_return(*, start_price: float, end_price: float) -> float:
    if start_price <= 0:
        raise ValueError("start_price must be positive")
    return (end_price / start_price) - 1.0


def compute_gross_total_return(
    *,
    start_date: date,
    end_date: date,
    start_price: float | None,
    end_price: float | None,
    dividends: Sequence[DividendCashPoint] = (),
) -> PeriodReturnBreakdown:
    """Compute price / cash / gross total return for holding 1 share over (start, end].

    Dividend cash is summed for points with ex_date in (start_date, end_date].
    Missing dividend amounts → PARTIAL (prices still usable for price_return).
    Missing prices → NOT_READY.
    """
    reasons: list[str] = []
    if start_date >= end_date:
        return PeriodReturnBreakdown(
            start_date=start_date,
            end_date=end_date,
            start_price=start_price,
            end_price=end_price,
            price_return=None,
            dividend_cash=None,
            total_return_gross=None,
            quality=ReturnQuality.NOT_READY,
            reasons=("invalid_period",),
        )

    if start_price is None or end_price is None or start_price <= 0 or end_price < 0:
        reasons.append("missing_or_invalid_prices")
        return PeriodReturnBreakdown(
            start_date=start_date,
            end_date=end_date,
            start_price=start_price,
            end_price=end_price,
            price_return=None,
            dividend_cash=None,
            total_return_gross=None,
            quality=ReturnQuality.NOT_READY,
            reasons=tuple(reasons),
        )

    in_window = [
        d
        for d in dividends
        if d.ex_date is not None and start_date < d.ex_date <= end_date
    ]
    with_amount = [
        d for d in in_window if d.amount_per_share is not None and float(d.amount_per_share) >= 0
    ]
    missing_amount = len(in_window) - len(with_amount)
    if missing_amount:
        reasons.append("dividend_amount_missing")

    price_ret = compute_price_return(start_price=float(start_price), end_price=float(end_price))
    cash = float(sum(float(d.amount_per_share or 0.0) for d in with_amount))
    total_gross = ((float(end_price) - float(start_price)) + cash) / float(start_price)

    if missing_amount:
        quality = ReturnQuality.PARTIAL
    else:
        quality = ReturnQuality.READY

    return PeriodReturnBreakdown(
        start_date=start_date,
        end_date=end_date,
        start_price=float(start_price),
        end_price=float(end_price),
        price_return=price_ret,
        dividend_cash=cash,
        total_return_gross=total_gross,
        quality=quality,
        reasons=tuple(reasons),
        dividends_considered=len(in_window),
        dividends_with_amount=len(with_amount),
    )


@dataclass
class DividendCoverageReport:
    """Universe-level readiness for gross total return research."""

    quality: ReturnQuality
    instruments_with_price_history: int = 0
    dividend_events_stored: int = 0
    instruments_with_dividend_events: int = 0
    coverage_ratio: float | None = None
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    mode: str = TOTAL_RETURN_MODE
    simulator_status: str = SIMULATOR_TOTAL_RETURN_STATUS

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality.value,
            "verdict": self.quality.value,
            "instruments_with_price_history": self.instruments_with_price_history,
            "dividend_events_stored": self.dividend_events_stored,
            "instruments_with_dividend_events": self.instruments_with_dividend_events,
            "coverage_ratio": self.coverage_ratio,
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "mode": self.mode,
            "tax_treatment": "gross_pre_tax",
            "simulator_total_return_mode": self.simulator_status,
            "dataset_mutation": False,
            "training": False,
        }


def assess_dividend_coverage(
    *,
    instruments_with_price_history: int,
    dividend_events_stored: int,
    instruments_with_dividend_events: int,
    accepted_provider: bool = False,
) -> DividendCoverageReport:
    notes = [
        "RAW market.candles remain price-only; total return is a derived view.",
        "Gross = price change + cash dividends; taxes/commissions excluded.",
        f"Simulator TOTAL_RETURN_GROSS_V1: {SIMULATOR_TOTAL_RETURN_STATUS}.",
    ]
    reasons: list[str] = []
    if instruments_with_price_history <= 0:
        reasons.append("no_price_history")
        return DividendCoverageReport(
            quality=ReturnQuality.NOT_READY,
            instruments_with_price_history=0,
            dividend_events_stored=dividend_events_stored,
            instruments_with_dividend_events=instruments_with_dividend_events,
            reasons=reasons,
            notes=notes,
        )

    ratio = (
        instruments_with_dividend_events / instruments_with_price_history
        if instruments_with_price_history
        else None
    )

    if not accepted_provider and dividend_events_stored == 0:
        reasons.append("no_accepted_dividend_provider")
        reasons.append("dividend_events_empty")
        return DividendCoverageReport(
            quality=ReturnQuality.NOT_READY,
            instruments_with_price_history=instruments_with_price_history,
            dividend_events_stored=0,
            instruments_with_dividend_events=0,
            coverage_ratio=0.0,
            reasons=reasons,
            notes=notes,
        )

    if ratio is not None and ratio < 0.5:
        reasons.append("dividend_instrument_coverage_below_50pct")
        return DividendCoverageReport(
            quality=ReturnQuality.PARTIAL,
            instruments_with_price_history=instruments_with_price_history,
            dividend_events_stored=dividend_events_stored,
            instruments_with_dividend_events=instruments_with_dividend_events,
            coverage_ratio=ratio,
            reasons=reasons,
            notes=notes,
        )

    return DividendCoverageReport(
        quality=ReturnQuality.READY,
        instruments_with_price_history=instruments_with_price_history,
        dividend_events_stored=dividend_events_stored,
        instruments_with_dividend_events=instruments_with_dividend_events,
        coverage_ratio=ratio,
        reasons=reasons,
        notes=notes,
    )
