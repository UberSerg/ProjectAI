"""Bounded bond purchase + hold-to-maturity accounting preview (pre-tax)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.modules.investment.domain.fixed_income import (
    TransactionCostProfile,
    calculate_bond_purchase,
)


@dataclass(frozen=True, slots=True)
class BondCashflowLeg:
    cashflow_date: date
    cashflow_type: str
    amount_per_bond: Decimal


@dataclass(frozen=True, slots=True)
class BondAccountingPreview:
    symbol: str
    lots: int
    quantity: int
    clean_price_percent: Decimal
    nkd_per_bond: Decimal
    clean_total: Decimal
    nkd_total: Decimal
    dirty_purchase: Decimal
    fees: Decimal
    cash_required: Decimal
    coupon_total: Decimal
    amortization_total: Decimal
    redemption_total: Decimal
    offer_total: Decimal
    total_inflows: Decimal
    total_return_before_tax: Decimal
    ytm_source: str | None
    ytm_value: Decimal | None
    ytm_note: str
    legs: tuple[BondCashflowLeg, ...]


def preview_hold_to_maturity(
    *,
    symbol: str,
    nominal: Decimal,
    clean_price_percent: Decimal,
    nkd_per_bond: Decimal,
    lots: int,
    lot_size: int,
    costs: TransactionCostProfile,
    future_legs: list[BondCashflowLeg],
    ytm_value: Decimal | None = None,
    ytm_source: str | None = None,
    has_future_offer: bool = False,
) -> BondAccountingPreview:
    """Dirty purchase vs observed future cashflows; taxes not modeled."""
    purchase = calculate_bond_purchase(
        nominal=nominal,
        clean_price_percent=clean_price_percent,
        accrued_interest_per_bond=nkd_per_bond,
        lots=lots,
        lot_size=lot_size,
        fees=Decimal("0"),
    )
    fees = costs.fee(purchase.dirty_total)
    cash_required = purchase.dirty_total + fees
    qty = Decimal(purchase.quantity)

    coupon = amort = redeem = offer = Decimal("0")
    scaled: list[BondCashflowLeg] = []
    for leg in future_legs:
        total = leg.amount_per_bond * qty
        scaled.append(
            BondCashflowLeg(leg.cashflow_date, leg.cashflow_type, total)
        )
        if leg.cashflow_type == "COUPON":
            coupon += total
        elif leg.cashflow_type == "AMORTIZATION":
            amort += total
        elif leg.cashflow_type == "REDEMPTION":
            redeem += total
        elif leg.cashflow_type == "OFFER":
            offer += total

    inflows = coupon + amort + redeem  # offers never auto-assumed as inflow
    note = (
        "MOEX YIELD observed on board; basis (offer vs maturity) not separately confirmed."
        if ytm_value is not None
        else "YTM not computed locally in V1 without full convention audit."
    )
    if has_future_offer:
        note += " Future offer exists — do not treat YTM to maturity as the only truth."

    return BondAccountingPreview(
        symbol=symbol,
        lots=lots,
        quantity=purchase.quantity,
        clean_price_percent=clean_price_percent,
        nkd_per_bond=nkd_per_bond,
        clean_total=purchase.clean_total,
        nkd_total=purchase.accrued_interest_total,
        dirty_purchase=purchase.dirty_total,
        fees=fees,
        cash_required=cash_required,
        coupon_total=coupon,
        amortization_total=amort,
        redemption_total=redeem,
        offer_total=offer,
        total_inflows=inflows,
        total_return_before_tax=inflows - cash_required,
        ytm_source=ytm_source,
        ytm_value=ytm_value,
        ytm_note=note,
        legs=tuple(scaled),
    )
