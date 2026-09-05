"""Bond cashflow schedule analysis and SUPPORTED V1 classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.modules.investment.domain.currency import CanonicalCurrency, resolve_nominal_currency
from app.modules.investment.domain.fixed_income import BondSupportStatus


class CashflowKnownAtQuality(StrEnum):
    """How reliably we know when a cashflow schedule was knowable."""

    EXACT_TIMESTAMP = "EXACT_TIMESTAMP"
    DATE_ONLY = "DATE_ONLY"
    CURRENT_STATE_ONLY = "CURRENT_STATE_ONLY"
    UNKNOWN = "UNKNOWN"


# MOEX bondization has no publication timestamp → live schedule is current-state.
MOEX_BONDIZATION_KNOWN_AT_QUALITY = CashflowKnownAtQuality.CURRENT_STATE_ONLY


@dataclass(frozen=True, slots=True)
class ScheduleCoupon:
    coupon_date: date
    amount: Decimal | None
    rate_percent: Decimal | None
    face_value: Decimal | None
    currency: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ScheduleAmortization:
    amort_date: date
    amount: Decimal | None
    value_percent: Decimal | None
    face_value: Decimal | None
    data_source: str | None
    currency: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ScheduleOffer:
    offer_date: date
    price: Decimal | None
    offer_type: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ScheduleEvidence:
    coupons: tuple[ScheduleCoupon, ...]
    amortizations: tuple[ScheduleAmortization, ...]
    offers: tuple[ScheduleOffer, ...]
    known_at_quality: CashflowKnownAtQuality = MOEX_BONDIZATION_KNOWN_AT_QUALITY


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def parse_bondization_schedule(
    *,
    coupons: list[dict[str, Any]],
    amortizations: list[dict[str, Any]],
    offers: list[dict[str, Any]],
) -> ScheduleEvidence:
    parsed_coupons: list[ScheduleCoupon] = []
    for row in coupons:
        d = _parse_date(row.get("coupondate"))
        if d is None:
            continue
        face_unit = row.get("faceunit")
        currency = None
        if face_unit not in (None, ""):
            currency = resolve_nominal_currency(face_unit=str(face_unit)).canonical
            if currency == CanonicalCurrency.UNKNOWN.value:
                currency = str(face_unit).upper()
        parsed_coupons.append(
            ScheduleCoupon(
                coupon_date=d,
                amount=_dec(row.get("value")),
                rate_percent=_dec(row.get("valueprc")),
                face_value=_dec(row.get("facevalue")),
                currency=currency,
                raw=dict(row),
            )
        )

    parsed_amorts: list[ScheduleAmortization] = []
    for row in amortizations:
        d = _parse_date(row.get("amortdate"))
        if d is None:
            continue
        face_unit = row.get("faceunit")
        currency = None
        if face_unit not in (None, ""):
            currency = resolve_nominal_currency(face_unit=str(face_unit)).canonical
        parsed_amorts.append(
            ScheduleAmortization(
                amort_date=d,
                amount=_dec(row.get("value")),
                value_percent=_dec(row.get("valueprc")),
                face_value=_dec(row.get("facevalue")),
                data_source=str(row.get("data_source") or "") or None,
                currency=currency,
                raw=dict(row),
            )
        )

    parsed_offers: list[ScheduleOffer] = []
    for row in offers:
        d = _parse_date(row.get("offerdate"))
        if d is None:
            continue
        parsed_offers.append(
            ScheduleOffer(
                offer_date=d,
                price=_dec(row.get("price")),
                offer_type=str(row.get("offertype") or "") or None,
                raw=dict(row),
            )
        )

    return ScheduleEvidence(
        coupons=tuple(sorted(parsed_coupons, key=lambda c: c.coupon_date)),
        amortizations=tuple(sorted(parsed_amorts, key=lambda a: a.amort_date)),
        offers=tuple(sorted(parsed_offers, key=lambda o: o.offer_date)),
    )


def coupon_structure_fixed(
    schedule: ScheduleEvidence, *, as_of: date | None = None
) -> bool:
    """True when remaining (or all) observed coupon rates/amounts are constant."""
    coupons = list(schedule.coupons)
    if as_of is not None:
        coupons = [c for c in coupons if c.coupon_date >= as_of]
    rates = [c.rate_percent for c in coupons if c.rate_percent is not None]
    amounts = [c.amount for c in coupons if c.amount is not None]
    if not rates and not amounts:
        return False
    if rates:
        return len({r for r in rates}) == 1
    return len({a for a in amounts}) == 1


def has_complex_amortization(schedule: ScheduleEvidence) -> bool:
    """Intermediate principal reductions (not a single maturity redemption)."""
    non_maturity = [
        a
        for a in schedule.amortizations
        if (a.data_source or "").lower() != "maturity"
    ]
    if len(non_maturity) >= 1:
        return True
    # Multiple rows even if unlabeled — treat as complex.
    return len(schedule.amortizations) > 1


def future_offers(schedule: ScheduleEvidence, as_of: date) -> list[ScheduleOffer]:
    return [o for o in schedule.offers if o.offer_date >= as_of]


def remaining_coupons(schedule: ScheduleEvidence, as_of: date) -> list[ScheduleCoupon]:
    return [c for c in schedule.coupons if c.coupon_date >= as_of]


def classify_bond_support_v1(
    *,
    face_unit: str | None,
    currency_id: str | None = None,
    nominal: float | None,
    lot_size: int | None,
    maturity_date: date | None,
    schedule: ScheduleEvidence | None,
    market_price_percent: float | None,
    as_of: date,
    perpetual_or_structured: bool = False,
) -> tuple[BondSupportStatus, list[str]]:
    """Strict SUPPORTED V1: observed schedule, no guessed cashflows.

    Corporate credit quality is orthogonal — SUPPORTED here means accounting
    cashflows are trustworthy, not that the bond is safe to buy.
    """
    reasons: list[str] = []
    face = resolve_nominal_currency(face_unit=face_unit, currency_id=currency_id)
    if face.canonical != CanonicalCurrency.RUB.value:
        reasons.append("currency_not_rub")
        return BondSupportStatus.UNSUPPORTED, reasons

    if perpetual_or_structured:
        reasons.append("perpetual_or_structured")
        return BondSupportStatus.UNSUPPORTED, reasons

    if nominal is None:
        reasons.append("missing_nominal")
    if lot_size is None or lot_size <= 0:
        reasons.append("missing_lot_size")
    if maturity_date is None:
        reasons.append("missing_maturity")
    if market_price_percent is None:
        reasons.append("missing_market_price")

    if schedule is None or not schedule.coupons:
        reasons.append("missing_coupon_schedule")
        return BondSupportStatus.RESEARCH_ONLY, reasons

    if schedule.known_at_quality is CashflowKnownAtQuality.CURRENT_STATE_ONLY:
        # Allowed for live as-of-now accounting; recorded as limitation, not a hard reject.
        pass

    remaining = remaining_coupons(schedule, as_of)
    if not remaining:
        reasons.append("no_remaining_coupons")
    elif any(c.amount is None for c in remaining):
        reasons.append("unfixed_future_coupon_amount")

    if not coupon_structure_fixed(schedule, as_of=as_of):
        reasons.append("coupon_structure_not_fixed")

    if has_complex_amortization(schedule):
        reasons.append("complex_amortization")

    if future_offers(schedule, as_of):
        reasons.append("offer_requires_policy")

    # Need a maturity redemption amount from amort maturity row or nominal.
    maturity_amort = [
        a
        for a in schedule.amortizations
        if (a.data_source or "").lower() == "maturity" or a.amort_date == maturity_date
    ]
    if not maturity_amort and maturity_date is not None:
        reasons.append("missing_redemption_cashflow")
    elif maturity_amort and any(a.amount is None for a in maturity_amort):
        reasons.append("missing_redemption_amount")

    if reasons:
        return BondSupportStatus.RESEARCH_ONLY, reasons
    return BondSupportStatus.SUPPORTED, []


def reason_code_ru(code: str) -> str:
    mapping = {
        "currency_not_rub": "Номинал не в рублях",
        "missing_nominal": "Неизвестен номинал",
        "missing_lot_size": "Неизвестен размер лота",
        "missing_maturity": "Неизвестна дата погашения",
        "missing_market_price": "Нет пригодной рыночной цены",
        "missing_coupon_schedule": "Нет графика купонов из источника",
        "no_remaining_coupons": "Нет оставшихся купонов",
        "unfixed_future_coupon_amount": "Будущие купоны без зафиксированной суммы",
        "coupon_structure_not_fixed": "Купонная структура не подтверждена как фиксированная",
        "complex_amortization": "Сложная амортизация номинала — нужен отдельный режим",
        "offer_requires_policy": "Есть будущая оферта без политики исполнения",
        "missing_redemption_cashflow": "Нет подтверждённого погашения",
        "missing_redemption_amount": "Сумма погашения не задана источником",
        "perpetual_or_structured": "Бессрочная / структурированная бумага",
        "coupon_not_observed_fixed": "Тип купона не подтверждён как фиксированный",
    }
    return mapping.get(code, code)


def _parse_date(value: Any) -> date | None:
    if value in (None, "", "0000-00-00"):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
