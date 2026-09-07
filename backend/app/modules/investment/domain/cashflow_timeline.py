"""Domain: Fixed Income cashflow timeline + portfolio projection (V1).

Events: BOND_COUPON, BOND_AMORTIZATION, BOND_REDEMPTION; OFFER is informational only.
Horizons: 30d / 90d / 12m gross. No double-count of redemption + final amort.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any


class CashflowEventType(StrEnum):
    BOND_COUPON = "BOND_COUPON"
    BOND_AMORTIZATION = "BOND_AMORTIZATION"
    BOND_REDEMPTION = "BOND_REDEMPTION"
    OFFER = "OFFER"  # informational — never counted in gross cash totals


@dataclass(frozen=True, slots=True)
class CashflowEvent:
    instrument_id: int
    symbol: str
    event_date: date
    event_type: CashflowEventType
    amount_per_unit: Decimal | None
    units: Decimal
    gross_amount: Decimal | None
    currency: str | None
    informational: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "event_date": self.event_date.isoformat(),
            "event_type": self.event_type.value,
            "amount_per_unit": float(self.amount_per_unit) if self.amount_per_unit is not None else None,
            "units": float(self.units),
            "gross_amount": float(self.gross_amount) if self.gross_amount is not None else None,
            "currency": self.currency,
            "informational": self.informational,
        }


@dataclass(frozen=True, slots=True)
class HorizonTotals:
    days: int
    gross: Decimal
    coupon: Decimal
    amortization: Decimal
    redemption: Decimal
    event_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "gross": float(self.gross),
            "coupon": float(self.coupon),
            "amortization": float(self.amortization),
            "redemption": float(self.redemption),
            "event_count": self.event_count,
        }


def map_stored_cashflow_type(cashflow_type: str) -> CashflowEventType | None:
    raw = (cashflow_type or "").upper()
    if raw == "COUPON":
        return CashflowEventType.BOND_COUPON
    if raw == "AMORTIZATION":
        return CashflowEventType.BOND_AMORTIZATION
    if raw == "REDEMPTION":
        return CashflowEventType.BOND_REDEMPTION
    if raw == "OFFER":
        return CashflowEventType.OFFER
    return None


def dedupe_redemption_amort(
    rows: Sequence[tuple[date, str, Decimal | None, str | None]],
) -> list[tuple[date, CashflowEventType, Decimal | None, str | None]]:
    """Drop final AMORTIZATION when REDEMPTION exists on the same date (no double-count)."""
    by_date: dict[date, list[tuple[str, Decimal | None, str | None]]] = {}
    for d, cf_type, amount, currency in rows:
        by_date.setdefault(d, []).append((cf_type, amount, currency))

    out: list[tuple[date, CashflowEventType, Decimal | None, str | None]] = []
    for d in sorted(by_date):
        items = by_date[d]
        types = {(t or "").upper() for t, _, _ in items}
        drop_amort = "REDEMPTION" in types and "AMORTIZATION" in types
        for cf_type, amount, currency in items:
            mapped = map_stored_cashflow_type(cf_type)
            if mapped is None:
                continue
            if drop_amort and mapped is CashflowEventType.BOND_AMORTIZATION:
                continue
            out.append((d, mapped, amount, currency))
    return out


def build_instrument_timeline(
    *,
    instrument_id: int,
    symbol: str,
    units: Decimal,
    cashflows: Sequence[tuple[date, str, Decimal | None, str | None]],
    as_of: date,
) -> list[CashflowEvent]:
    events: list[CashflowEvent] = []
    for event_date, event_type, amount, currency in dedupe_redemption_amort(cashflows):
        if event_date < as_of:
            continue
        informational = event_type is CashflowEventType.OFFER
        per = amount
        gross = None if per is None or informational else (per * units)
        events.append(
            CashflowEvent(
                instrument_id=instrument_id,
                symbol=symbol,
                event_date=event_date,
                event_type=event_type,
                amount_per_unit=per,
                units=units,
                gross_amount=gross,
                currency=currency,
                informational=informational,
            )
        )
    return events


def sum_horizon(events: Sequence[CashflowEvent], *, as_of: date, days: int) -> HorizonTotals:
    end = as_of + timedelta(days=days)
    coupon = Decimal("0")
    amort = Decimal("0")
    redemption = Decimal("0")
    count = 0
    for ev in events:
        if ev.informational or ev.gross_amount is None:
            continue
        if not (as_of < ev.event_date <= end):
            continue
        count += 1
        if ev.event_type is CashflowEventType.BOND_COUPON:
            coupon += ev.gross_amount
        elif ev.event_type is CashflowEventType.BOND_AMORTIZATION:
            amort += ev.gross_amount
        elif ev.event_type is CashflowEventType.BOND_REDEMPTION:
            redemption += ev.gross_amount
    return HorizonTotals(
        days=days,
        gross=coupon + amort + redemption,
        coupon=coupon,
        amortization=amort,
        redemption=redemption,
        event_count=count,
    )


def project_portfolio_cashflows(
    *,
    events: Sequence[CashflowEvent],
    as_of: date,
) -> dict[str, Any]:
    horizons = {
        "30d": sum_horizon(events, as_of=as_of, days=30),
        "90d": sum_horizon(events, as_of=as_of, days=90),
        "12m": sum_horizon(events, as_of=as_of, days=365),
    }
    next_payment = None
    for ev in sorted(events, key=lambda e: (e.event_date, e.event_type.value)):
        if ev.informational or ev.gross_amount is None:
            continue
        if ev.event_date >= as_of:
            next_payment = ev.to_dict()
            break
    return {
        "as_of": as_of.isoformat(),
        "horizons": {k: v.to_dict() for k, v in horizons.items()},
        "events": [e.to_dict() for e in sorted(events, key=lambda x: (x.event_date, x.symbol))],
        "next_payment": next_payment,
        "note": (
            "Gross cashflows before tax/commission. Offers are informational only. "
            "Redemption and final amortization on the same date are not double-counted."
        ),
    }
