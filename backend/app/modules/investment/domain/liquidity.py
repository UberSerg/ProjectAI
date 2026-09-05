"""Liquidity foundation V0 — framework-free.

Do not invent bid-ask spread when not observed.
Statuses: GOOD / MEDIUM / LOW / UNKNOWN — documented thresholds, not optimized.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class LiquidityStatus(StrEnum):
    GOOD = "GOOD"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class LiquidityReason(StrEnum):
    STALE_PRICE = "STALE_PRICE"
    LOW_VOLUME = "LOW_VOLUME"
    NO_RECENT_TRADES = "NO_RECENT_TRADES"
    UNKNOWN_LIQUIDITY = "UNKNOWN_LIQUIDITY"


# Documented research thresholds — not historically optimized.
GOOD_MAX_DAYS = 1
MEDIUM_MAX_DAYS = 5
LOW_VOLUME_THRESHOLD = 0.0


@dataclass(frozen=True, slots=True)
class LiquidityAssessment:
    instrument_id: int
    volume: float | None
    turnover: float | None
    trade_count: int | None
    last_trade_date: date | None
    days_since_trade: int | None
    spread_if_available: float | None
    liquidity_status: LiquidityStatus
    source: str
    risk_flags: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    limitations: tuple[str, ...] = (
        "Spread invented only when observed — usually None in V0",
        "Bond marketdata VALTODAY/NUMTRADES not yet ingested into typed columns",
        "Candle volume used when available as proxy",
    )


@dataclass(frozen=True, slots=True)
class LiquidityEligibility:
    eligible_for_defensive_research: bool
    reasons: tuple[str, ...]
    liquidity_status: LiquidityStatus


def assess_liquidity(
    *,
    instrument_id: int,
    as_of: date,
    last_trade_date: date | None,
    volume: float | None = None,
    turnover: float | None = None,
    trade_count: int | None = None,
    spread: float | None = None,
    source: str = "BOND_SNAPSHOT_AND_OR_CANDLES",
) -> LiquidityAssessment:
    reasons: list[str] = []
    flags: list[str] = []

    if last_trade_date is None and volume is None and trade_count is None:
        reasons.append(LiquidityReason.UNKNOWN_LIQUIDITY.value)
        flags.append("UNKNOWN_LIQUIDITY")
        return LiquidityAssessment(
            instrument_id=instrument_id,
            volume=volume,
            turnover=turnover,
            trade_count=trade_count,
            last_trade_date=None,
            days_since_trade=None,
            spread_if_available=spread,
            liquidity_status=LiquidityStatus.UNKNOWN,
            source=source,
            risk_flags=tuple(flags),
            reasons=tuple(reasons),
        )

    days = (as_of - last_trade_date).days if last_trade_date is not None else None

    if days is None:
        reasons.append(LiquidityReason.UNKNOWN_LIQUIDITY.value)
        flags.append("UNKNOWN_LIQUIDITY")
        status = LiquidityStatus.UNKNOWN
    elif days > MEDIUM_MAX_DAYS:
        reasons.append(LiquidityReason.STALE_PRICE.value)
        reasons.append(LiquidityReason.NO_RECENT_TRADES.value)
        flags.append("LOW_LIQUIDITY")
        status = LiquidityStatus.LOW
    elif days > GOOD_MAX_DAYS:
        reasons.append(LiquidityReason.STALE_PRICE.value)
        status = LiquidityStatus.MEDIUM
    else:
        status = LiquidityStatus.GOOD

    if volume is not None and volume <= LOW_VOLUME_THRESHOLD:
        reasons.append(LiquidityReason.LOW_VOLUME.value)
        flags.append("LOW_LIQUIDITY")
        if status is LiquidityStatus.GOOD:
            status = LiquidityStatus.MEDIUM
        elif status is LiquidityStatus.MEDIUM:
            status = LiquidityStatus.LOW

    if trade_count is not None and trade_count <= 0:
        reasons.append(LiquidityReason.NO_RECENT_TRADES.value)
        flags.append("LOW_LIQUIDITY")
        if status is not LiquidityStatus.UNKNOWN:
            status = LiquidityStatus.LOW

    return LiquidityAssessment(
        instrument_id=instrument_id,
        volume=volume,
        turnover=turnover,
        trade_count=trade_count,
        last_trade_date=last_trade_date,
        days_since_trade=days,
        spread_if_available=spread,
        liquidity_status=status,
        source=source,
        risk_flags=tuple(dict.fromkeys(flags)),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def liquidity_eligibility(assessment: LiquidityAssessment) -> LiquidityEligibility:
    ok = assessment.liquidity_status in {LiquidityStatus.GOOD, LiquidityStatus.MEDIUM}
    reasons = list(assessment.reasons)
    if assessment.liquidity_status is LiquidityStatus.UNKNOWN:
        reasons.append(LiquidityReason.UNKNOWN_LIQUIDITY.value)
        ok = False
    if assessment.liquidity_status is LiquidityStatus.LOW:
        ok = False
    return LiquidityEligibility(
        eligible_for_defensive_research=ok,
        reasons=tuple(dict.fromkeys(reasons)),
        liquidity_status=assessment.liquidity_status,
    )
