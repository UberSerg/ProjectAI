"""Fixed Income Cashflow Coverage V1 tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.investment.domain.accounting import BondCashflowLeg, preview_hold_to_maturity
from app.modules.investment.domain.cashflows import (
    CashflowKnownAtQuality,
    ScheduleAmortization,
    ScheduleCoupon,
    ScheduleEvidence,
    ScheduleOffer,
    classify_bond_support_v1,
    parse_bondization_schedule,
)
from app.modules.investment.domain.fixed_income import (
    BondSupportStatus,
    BondType,
    CreditQualityStatus,
    TransactionCostProfile,
    real_portfolio_eligible,
)


def _coupon(d: str, value: float | None, prc: float | None = 7.1, face: float = 1000) -> ScheduleCoupon:
    return ScheduleCoupon(
        coupon_date=date.fromisoformat(d),
        amount=None if value is None else Decimal(str(value)),
        rate_percent=None if prc is None else Decimal(str(prc)),
        face_value=Decimal(str(face)),
        currency="RUB",
        raw={"coupondate": d, "value": value, "valueprc": prc},
    )


def _amort(
    d: str, value: float, *, source: str = "maturity", face: float = 1000
) -> ScheduleAmortization:
    return ScheduleAmortization(
        amort_date=date.fromisoformat(d),
        amount=Decimal(str(value)),
        value_percent=Decimal("100") if source == "maturity" else Decimal("12.5"),
        face_value=Decimal(str(face)),
        data_source=source,
        currency="RUB",
        raw={"amortdate": d, "value": value, "data_source": source},
    )


def test_simple_valid_rub_fixed_bond_is_supported() -> None:
    schedule = ScheduleEvidence(
        coupons=(
            _coupon("2026-12-01", 35.4),
            _coupon("2027-06-01", 35.4),
        ),
        amortizations=(_amort("2030-01-01", 1000),),
        offers=(),
        known_at_quality=CashflowKnownAtQuality.CURRENT_STATE_ONLY,
    )
    status, reasons = classify_bond_support_v1(
        face_unit="SUR",
        nominal=1000,
        lot_size=1,
        maturity_date=date(2030, 1, 1),
        schedule=schedule,
        market_price_percent=98.5,
        as_of=date(2026, 9, 5),
    )
    assert status is BondSupportStatus.SUPPORTED
    assert reasons == []


def test_missing_coupon_schedule_is_research_only() -> None:
    status, reasons = classify_bond_support_v1(
        face_unit="RUB",
        nominal=1000,
        lot_size=1,
        maturity_date=date(2030, 1, 1),
        schedule=None,
        market_price_percent=100,
        as_of=date(2026, 9, 5),
    )
    assert status is BondSupportStatus.RESEARCH_ONLY
    assert "missing_coupon_schedule" in reasons


def test_fx_nominal_unsupported() -> None:
    schedule = ScheduleEvidence(
        coupons=(_coupon("2027-01-01", 10),),
        amortizations=(_amort("2030-01-01", 1000),),
        offers=(),
    )
    status, reasons = classify_bond_support_v1(
        face_unit="USD",
        currency_id="SUR",
        nominal=1000,
        lot_size=1,
        maturity_date=date(2030, 1, 1),
        schedule=schedule,
        market_price_percent=100,
        as_of=date(2026, 9, 5),
    )
    assert status is BondSupportStatus.UNSUPPORTED
    assert "currency_not_rub" in reasons


def test_unfixed_future_coupon_is_research_only() -> None:
    schedule = ScheduleEvidence(
        coupons=(
            _coupon("2026-12-01", 35.4),
            _coupon("2027-06-01", None, None),
        ),
        amortizations=(_amort("2030-01-01", 1000),),
        offers=(),
    )
    status, reasons = classify_bond_support_v1(
        face_unit="RUB",
        nominal=1000,
        lot_size=1,
        maturity_date=date(2030, 1, 1),
        schedule=schedule,
        market_price_percent=100,
        as_of=date(2026, 9, 5),
    )
    assert status is BondSupportStatus.RESEARCH_ONLY
    assert "unfixed_future_coupon_amount" in reasons


def test_complex_amortization_is_research_only() -> None:
    schedule = ScheduleEvidence(
        coupons=(_coupon("2026-12-01", 20), _coupon("2027-12-01", 20)),
        amortizations=(
            _amort("2026-12-01", 125, source="amortization", face=875),
            _amort("2030-01-01", 875, source="maturity", face=875),
        ),
        offers=(),
    )
    status, reasons = classify_bond_support_v1(
        face_unit="RUB",
        nominal=1000,
        lot_size=1,
        maturity_date=date(2030, 1, 1),
        schedule=schedule,
        market_price_percent=100,
        as_of=date(2026, 9, 5),
    )
    assert status is BondSupportStatus.RESEARCH_ONLY
    assert "complex_amortization" in reasons


def test_future_offer_is_research_only_and_does_not_auto_close() -> None:
    schedule = ScheduleEvidence(
        coupons=(_coupon("2026-12-01", 35.4), _coupon("2027-06-01", 35.4)),
        amortizations=(_amort("2030-01-01", 1000),),
        offers=(
            ScheduleOffer(
                offer_date=date(2027, 1, 1),
                price=Decimal("100"),
                offer_type="put",
                raw={},
            ),
        ),
    )
    status, reasons = classify_bond_support_v1(
        face_unit="RUB",
        nominal=1000,
        lot_size=1,
        maturity_date=date(2030, 1, 1),
        schedule=schedule,
        market_price_percent=100,
        as_of=date(2026, 9, 5),
    )
    assert status is BondSupportStatus.RESEARCH_ONLY
    assert "offer_requires_policy" in reasons

    preview = preview_hold_to_maturity(
        symbol="X",
        nominal=Decimal("1000"),
        clean_price_percent=Decimal("100"),
        nkd_per_bond=Decimal("0"),
        lots=1,
        lot_size=1,
        costs=TransactionCostProfile(Decimal("0")),
        future_legs=[
            BondCashflowLeg(date(2026, 12, 1), "COUPON", Decimal("35.4")),
            BondCashflowLeg(date(2030, 1, 1), "REDEMPTION", Decimal("1000")),
        ],
        has_future_offer=True,
    )
    # Offer is not counted as automatic inflow.
    assert preview.offer_total == 0
    assert preview.total_inflows == Decimal("1035.4")


def test_perpetual_or_structured_unsupported() -> None:
    schedule = ScheduleEvidence(
        coupons=(_coupon("2027-01-01", 10),),
        amortizations=(),
        offers=(),
    )
    status, reasons = classify_bond_support_v1(
        face_unit="RUB",
        nominal=1000,
        lot_size=1,
        maturity_date=date(2030, 1, 1),
        schedule=schedule,
        market_price_percent=100,
        as_of=date(2026, 9, 5),
        perpetual_or_structured=True,
    )
    assert status is BondSupportStatus.UNSUPPORTED
    assert "perpetual_or_structured" in reasons


def test_corporate_without_rating_not_real_money_eligible() -> None:
    assert not real_portfolio_eligible(BondType.CORPORATE, CreditQualityStatus.UNKNOWN)


def test_parse_bondization_and_coupon_once_semantics() -> None:
    schedule = parse_bondization_schedule(
        coupons=[
            {
                "coupondate": "2026-12-01",
                "value": 35.4,
                "valueprc": 7.1,
                "facevalue": 1000,
                "faceunit": "RUB",
            },
            {
                "coupondate": "2026-12-01",
                "value": 35.4,
                "valueprc": 7.1,
                "facevalue": 1000,
                "faceunit": "RUB",
            },
        ],
        amortizations=[
            {
                "amortdate": "2030-01-01",
                "value": 1000,
                "valueprc": 100,
                "facevalue": 1000,
                "faceunit": "RUB",
                "data_source": "maturity",
            }
        ],
        offers=[],
    )
    # Parser keeps rows; idempotent DB unique key prevents duplicate persist.
    assert len(schedule.coupons) == 2
    assert schedule.coupons[0].amount == Decimal("35.4")
    assert schedule.amortizations[0].amount == Decimal("1000")


def test_accounting_amount_times_integer_quantity() -> None:
    preview = preview_hold_to_maturity(
        symbol="OFZ",
        nominal=Decimal("1000"),
        clean_price_percent=Decimal("98"),
        nkd_per_bond=Decimal("12.5"),
        lots=2,
        lot_size=1,
        costs=TransactionCostProfile(Decimal("0")),
        future_legs=[
            BondCashflowLeg(date(2026, 12, 1), "COUPON", Decimal("35.4")),
            BondCashflowLeg(date(2030, 1, 1), "REDEMPTION", Decimal("1000")),
        ],
        ytm_value=Decimal("7.5"),
        ytm_source="MOEX_BOARD_YIELD",
    )
    assert preview.quantity == 2
    assert preview.dirty_purchase == Decimal("1985.0")
    assert preview.coupon_total == Decimal("70.8")
    assert preview.redemption_total == Decimal("2000")
    assert preview.total_return_before_tax == preview.total_inflows - preview.cash_required


def test_current_state_only_quality_constant() -> None:
    assert CashflowKnownAtQuality.CURRENT_STATE_ONLY.value == "CURRENT_STATE_ONLY"


def test_amortization_not_double_counted_as_redemption_in_classifier() -> None:
    # Complex amorts block SUPPORTED; redemption still represented separately in ingest.
    schedule = ScheduleEvidence(
        coupons=(_coupon("2026-12-01", 10),),
        amortizations=(
            _amort("2025-01-01", 200, source="amortization", face=800),
            _amort("2030-01-01", 800, source="maturity", face=800),
        ),
        offers=(),
    )
    status, reasons = classify_bond_support_v1(
        face_unit="RUB",
        nominal=1000,
        lot_size=1,
        maturity_date=date(2030, 1, 1),
        schedule=schedule,
        market_price_percent=100,
        as_of=date(2026, 9, 5),
    )
    assert status is BondSupportStatus.RESEARCH_ONLY
    assert "complex_amortization" in reasons
