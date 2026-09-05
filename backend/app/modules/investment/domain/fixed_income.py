"""Conservative fixed-income domain primitives."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum


class BondType(StrEnum):
    GOVERNMENT = "Government"
    CORPORATE = "Corporate"
    MUNICIPAL = "Municipal"


class BondSupportStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    UNSUPPORTED = "UNSUPPORTED"


class CreditQualityStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    OBSERVED = "OBSERVED"


class BondCashflowType(StrEnum):
    COUPON = "COUPON"
    AMORTIZATION = "AMORTIZATION"
    REDEMPTION = "REDEMPTION"
    OFFER = "OFFER"


class TaxModelStatus(StrEnum):
    NOT_MODELED = "NOT_MODELED"


SETTLEMENT_NOT_MODELED_V0 = "SETTLEMENT_NOT_MODELED_V0"


def real_portfolio_eligible(bond_type: BondType, credit_quality: CreditQualityStatus) -> bool:
    """Unknown corporate credit quality is never silently treated as safe."""
    return not (bond_type is BondType.CORPORATE and credit_quality is CreditQualityStatus.UNKNOWN)


@dataclass(frozen=True)
class BondPurchase:
    quantity: int
    nominal_total: Decimal
    clean_total: Decimal
    accrued_interest_total: Decimal
    dirty_total: Decimal
    fees: Decimal
    cash_required: Decimal


def calculate_bond_purchase(
    *,
    nominal: Decimal,
    clean_price_percent: Decimal,
    accrued_interest_per_bond: Decimal,
    lots: int,
    lot_size: int = 1,
    fees: Decimal = Decimal("0"),
) -> BondPurchase:
    if nominal <= 0 or lot_size <= 0 or lots < 0:
        raise ValueError("nominal/lot_size must be positive and lots non-negative")
    quantity = lots * lot_size
    nominal_total = nominal * quantity
    clean_total = nominal_total * clean_price_percent / Decimal("100")
    nkd_total = accrued_interest_per_bond * quantity
    dirty_total = clean_total + nkd_total
    return BondPurchase(
        quantity=quantity,
        nominal_total=nominal_total,
        clean_total=clean_total,
        accrued_interest_total=nkd_total,
        dirty_total=dirty_total,
        fees=fees,
        cash_required=dirty_total + fees,
    )


@dataclass(frozen=True)
class TransactionCostProfile:
    broker_bps: Decimal
    exchange_bps: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("0")
    min_fee: Decimal = Decimal("0")

    def fee(self, notional: Decimal) -> Decimal:
        variable = notional * (self.broker_bps + self.exchange_bps) / Decimal("10000")
        return max(self.min_fee, variable)

    def execution_price(self, price: Decimal, side: str) -> Decimal:
        shift = self.slippage_bps / Decimal("10000")
        if side.upper() == "BUY":
            return price * (Decimal("1") + shift)
        if side.upper() == "SELL":
            return price * (Decimal("1") - shift)
        if side.upper() in {"COUPON", "REDEMPTION", "AMORTIZATION"}:
            return price
        raise ValueError(f"Unsupported side: {side}")


COST_PRESETS = {bps: TransactionCostProfile(Decimal(bps)) for bps in (0, 5, 10, 20)}


def affordable_lots(cash: Decimal, lot_notional: Decimal, profile: TransactionCostProfile) -> int:
    if cash <= 0 or lot_notional <= 0:
        return 0
    guess = int((cash / lot_notional).to_integral_value(rounding=ROUND_FLOOR))
    while guess and guess * lot_notional + profile.fee(guess * lot_notional) > cash:
        guess -= 1
    return guess
