"""Application services for Investment Foundation + Fixed Income Cashflow V1."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Date, cast, desc, func, select, text
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument, Series, SeriesValue
from app.modules.investment.domain.accounting import (
    BondCashflowLeg,
    preview_hold_to_maturity,
)
from app.modules.investment.domain.cashflows import reason_code_ru
from app.modules.investment.domain.currency import (
    CanonicalCurrency,
    display_currency_ru,
    resolve_nominal_currency,
)
from app.modules.investment.domain.fixed_income import (
    BondSupportStatus,
    BondType,
    CreditQualityStatus,
    TransactionCostProfile,
    real_portfolio_eligible,
)
from app.modules.investment.domain.hurdle import HurdleQuote, KnownAtQuality
from app.modules.investment.infrastructure.models import (
    BondCashflow,
    BondMarketSnapshot,
    BondTerm,
)


class CbrHurdleProvider:
    """PIT reader for existing market.KEY_RATE; CBR values are percentages."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def quote(self, as_of: date) -> HurdleQuote | None:
        row = self.session.execute(
            select(SeriesValue, Series)
            .join(Series, Series.id == SeriesValue.series_id)
            .where(
                Series.code == "KEY_RATE",
                cast(SeriesValue.timestamp, Date) <= as_of,
            )
            .order_by(desc(SeriesValue.timestamp))
            .limit(1)
        ).first()
        if row is None:
            return None
        value, series = row
        observation_date = value.timestamp.date()
        return HurdleQuote(
            as_of=observation_date,
            annual_rate=float(value.value) / 100,
            known_at=observation_date,
            known_at_quality=KnownAtQuality.DATE_ONLY,
            source=series.source,
        )


def key_rate_audit(
    rows: Iterable[dict[str, Any]],
    *,
    output: Path | None = None,
) -> dict[str, Any]:
    """Audit observed KEY_RATE rows; deliberately callable without a database."""
    materialized = list(rows)
    dates = [str(row["as_of"]) for row in materialized if row.get("as_of")]
    values = [float(row["annual_rate"]) for row in materialized if row.get("annual_rate") is not None]
    report = {
        "series_code": "KEY_RATE",
        "benchmark_type": "CBR_KEY_RATE",
        "source": "CBR KeyRateXML → market.series_values",
        "known_at_quality": "DATE_ONLY",
        "known_at_policy": (
            "Observation date only; no exact publication timestamp from CBR SOAP. "
            "Decision-time uses latest KEY_RATE with timestamp.date <= as_of."
        ),
        "not_risk_free": True,
        "rows": len(materialized),
        "first_as_of": min(dates) if dates else None,
        "last_as_of": max(dates) if dates else None,
        "latest_annual_rate": values[-1] if values else None,
        "min_annual_rate": min(values) if values else None,
        "max_annual_rate": max(values) if values else None,
        "duplicates_collapsed_by_provider": True,
        "timezone_note": "Stored as UTC midnight of the CBR observation date",
        "generated_at": datetime.now(UTC).isoformat(),
        "issues": [],
    }
    target = output or Path(".tmp/investment-foundation-v0/key-rate-audit.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def resolve_bond_face_currency(
    *,
    face_unit: str | None = None,
    currency_id: str | None = None,
) -> str | None:
    """Canonical nominal currency or None when UNKNOWN/missing."""
    resolved = resolve_nominal_currency(face_unit=face_unit, currency_id=currency_id)
    if resolved.canonical == CanonicalCurrency.UNKNOWN.value:
        return None
    return resolved.canonical


def classify_vanilla_rub_fixed_rate(
    *,
    currency: str | None,
    coupon_type: str | None,
    has_offer: bool,
    nominal: float | None,
    maturity_date: date | None,
    face_unit: str | None = None,
    currency_id: str | None = None,
) -> tuple[BondSupportStatus, list[str]]:
    """Legacy V0 helper kept for currency/offer unit tests."""
    reasons: list[str] = []
    face = resolve_nominal_currency(face_unit=face_unit, currency_id=currency_id)
    if face_unit is not None and str(face_unit).strip():
        resolved = face.canonical
    elif currency in {CanonicalCurrency.RUB.value, "USD", "CNY", "EUR"}:
        resolved = str(currency)
    else:
        resolved = face.canonical
    if resolved != CanonicalCurrency.RUB.value:
        reasons.append("currency_not_rub")
    if (coupon_type or "").upper() not in {"FIXED", "CONSTANT"}:
        reasons.append("coupon_not_observed_fixed")
    if nominal is None:
        reasons.append("missing_nominal")
    if maturity_date is None:
        reasons.append("missing_maturity")
    if resolved != CanonicalCurrency.RUB.value:
        return BondSupportStatus.UNSUPPORTED, reasons
    if has_offer:
        reasons.append("offer_requires_policy")
    return (
        (BondSupportStatus.SUPPORTED if not reasons else BondSupportStatus.RESEARCH_ONLY),
        reasons,
    )


def fixed_income_readiness(session: Session) -> dict[str, Any]:
    if not _schema_ready(session):
        return _not_ready("investment schema missing; apply alembic 20260905_0019")
    terms = int(session.scalar(select(func.count()).select_from(BondTerm)) or 0)
    cashflows = int(session.scalar(select(func.count()).select_from(BondCashflow)) or 0)
    coupons = int(
        session.scalar(select(func.count()).select_from(BondCashflow).where(BondCashflow.cashflow_type == "COUPON"))
        or 0
    )
    redemptions = int(
        session.scalar(select(func.count()).select_from(BondCashflow).where(BondCashflow.cashflow_type == "REDEMPTION"))
        or 0
    )
    amorts = int(
        session.scalar(
            select(func.count()).select_from(BondCashflow).where(BondCashflow.cashflow_type == "AMORTIZATION")
        )
        or 0
    )
    offers = int(
        session.scalar(select(func.count()).select_from(BondCashflow).where(BondCashflow.cashflow_type == "OFFER")) or 0
    )
    supported = int(
        session.scalar(select(func.count()).select_from(BondTerm).where(BondTerm.support_status == "SUPPORTED")) or 0
    )
    missing_nominal = int(
        session.scalar(select(func.count()).select_from(BondTerm).where(BondTerm.nominal.is_(None))) or 0
    )
    issues = []
    if not terms:
        issues.append({"code": "no_bond_terms", "severity": "BLOCKER"})
    if not cashflows:
        issues.append({"code": "no_observed_cashflows", "severity": "WARNING"})
    if missing_nominal:
        issues.append({"code": "missing_nominal", "severity": "BLOCKER", "count": missing_nominal})
    return {
        "status": "READY" if not any(i["severity"] == "BLOCKER" for i in issues) else "NOT_READY",
        "bond_terms": terms,
        "cashflows": cashflows,
        "coupon_cashflows": coupons,
        "redemption_cashflows": redemptions,
        "amortization_cashflows": amorts,
        "offer_cashflows": offers,
        "supported_bonds": supported,
        "issues": issues,
        "tax_model_status": "NOT_MODELED",
        "settlement_status": "SETTLEMENT_NOT_MODELED_V0",
        "flags": {
            "BOND_TERMS_READY": "READY" if terms else "NOT_READY",
            "COUPON_CASHFLOWS_READY": "READY" if coupons else "NOT_READY",
            "REDEMPTION_READY": "READY" if redemptions else "NOT_READY",
            "AMORTIZATION_PARTIAL": "PARTIAL" if amorts else "NOT_READY",
            "OFFER_POLICY_NOT_READY": "NOT_READY",
            "CREDIT_QUALITY_NOT_READY": "NOT_READY",
            "BOND_HISTORICAL_TOTAL_RETURN": "NOT_READY",
            "known_at_quality": "CURRENT_STATE_ONLY",
        },
    }


def investment_readiness(session: Session) -> dict[str, Any]:
    hurdle_ready = CbrHurdleProvider(session).quote(date.today()) is not None
    fixed_income = fixed_income_readiness(session)
    flags = fixed_income.get("flags") or {}
    checks = [
        {"code": "CBR_HURDLE_READY", "status": "READY" if hurdle_ready else "NOT_READY"},
        {"code": "FIXED_INCOME_DATA_READY", "status": fixed_income["status"]},
        {"code": "BOND_TERMS_READY", "status": flags.get("BOND_TERMS_READY", "NOT_READY")},
        {
            "code": "COUPON_CASHFLOWS_READY",
            "status": flags.get("COUPON_CASHFLOWS_READY", "NOT_READY"),
        },
        {"code": "REDEMPTION_READY", "status": flags.get("REDEMPTION_READY", "NOT_READY")},
        {
            "code": "AMORTIZATION_PARTIAL",
            "status": flags.get("AMORTIZATION_PARTIAL", "NOT_READY"),
        },
        {"code": "OFFER_POLICY_NOT_READY", "status": "NOT_READY"},
        {"code": "CREDIT_QUALITY_NOT_READY", "status": "NOT_READY"},
        {"code": "BOND_HISTORICAL_TOTAL_RETURN", "status": "NOT_READY"},
        {"code": "REALISTIC_LOTS_READY", "status": "READY"},
        {"code": "TRANSACTION_COSTS_READY", "status": "READY"},
        {"code": "ASSET_ALLOCATION_RESEARCH_READY", "status": "READY"},
        {"code": "TAX_MODEL_NOT_READY", "status": "NOT_READY"},
        {"code": "REAL_MONEY_NOT_READY", "status": "NOT_READY"},
    ]
    return {"status": "PARTIAL", "checks": checks, "fixed_income": fixed_income}


def list_bonds(session: Session, limit: int = 100) -> list[dict[str, Any]]:
    if not _schema_ready(session):
        return []
    rows = session.execute(
        select(Instrument, BondTerm)
        .join(BondTerm, BondTerm.instrument_id == Instrument.id)
        .where(Instrument.asset_class == "bond")
        .order_by(Instrument.symbol)
        .limit(limit)
    ).all()
    result = []
    today = date.today()
    for instrument, term in rows:
        bond_type = BondType(term.bond_type)
        credit = CreditQualityStatus(term.credit_quality_status)
        snap = session.scalar(
            select(BondMarketSnapshot)
            .where(BondMarketSnapshot.instrument_id == instrument.id)
            .order_by(desc(BondMarketSnapshot.as_of))
            .limit(1)
        )
        next_coupon = session.scalar(
            select(BondCashflow)
            .where(
                BondCashflow.instrument_id == instrument.id,
                BondCashflow.cashflow_type == "COUPON",
                BondCashflow.cashflow_date >= today,
            )
            .order_by(BondCashflow.cashflow_date)
            .limit(1)
        )
        reasons = list((term.raw_fields or {}).get("support_reasons") or [])
        result.append(
            {
                "instrument_id": instrument.id,
                "symbol": instrument.symbol,
                "name": instrument.name,
                "currency": term.currency or instrument.currency,
                "currency_display": display_currency_ru(term.currency or instrument.currency or "UNKNOWN"),
                "currency_raw": (term.raw_fields or {}).get("FACEUNIT"),
                "bond_type": bond_type.value,
                "nominal": float(term.nominal) if term.nominal is not None else None,
                "lot_size": term.lot_size,
                "maturity_date": term.maturity_date,
                "support_status": term.support_status,
                "credit_quality_status": credit.value,
                "real_portfolio_eligible": real_portfolio_eligible(bond_type, credit),
                "support_reasons": reasons,
                "support_reasons_ru": [reason_code_ru(code) for code in reasons],
                "why_not_supported": (
                    None
                    if term.support_status == "SUPPORTED"
                    else "; ".join(reason_code_ru(code) for code in reasons) or "Недостаточно надёжных данных"
                ),
                "credit_safety_note": (
                    "Kraken умеет корректно посчитать денежные потоки бумаги — "
                    "это не означает, что облигация безопасна."
                ),
                "clean_price_percent": (
                    float(snap.clean_price_percent) if snap and snap.clean_price_percent is not None else None
                ),
                "nkd": float(snap.accrued_interest) if snap and snap.accrued_interest is not None else None,
                "dirty_estimate": _dirty_estimate(term, snap),
                "ytm": float(snap.yield_value) if snap and snap.yield_value is not None else None,
                "ytm_note": (
                    "Наблюдаемый YIELD MOEX; база offer vs maturity отдельно не подтверждена."
                    if snap and snap.yield_value is not None
                    else None
                ),
                "duration": (term.raw_fields or {}).get("duration"),
                "next_coupon_date": next_coupon.cashflow_date if next_coupon else None,
                "next_coupon_amount": (
                    float(next_coupon.amount) if next_coupon and next_coupon.amount is not None else None
                ),
                "data_quality": {
                    "known_at_quality": (term.raw_fields or {}).get(
                        "bondization_known_at_quality", "CURRENT_STATE_ONLY"
                    ),
                    "source": term.source,
                },
            }
        )
    return result


def bond_accounting_preview(
    session: Session,
    *,
    symbol: str,
    lots: int = 1,
    cost_bps: Decimal = Decimal("5"),
    as_of: date | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    row = session.execute(
        select(Instrument, BondTerm)
        .join(BondTerm, BondTerm.instrument_id == Instrument.id)
        .where(Instrument.symbol == symbol)
        .limit(1)
    ).first()
    if row is None:
        return {"status": "NOT_FOUND", "symbol": symbol}
    instrument, term = row
    if term.support_status != "SUPPORTED":
        return {
            "status": "NOT_SUPPORTED",
            "symbol": symbol,
            "support_status": term.support_status,
            "reasons": (term.raw_fields or {}).get("support_reasons") or [],
            "note": "Live accounting preview only for SUPPORTED bonds.",
        }
    snap = session.scalar(
        select(BondMarketSnapshot)
        .where(BondMarketSnapshot.instrument_id == instrument.id)
        .order_by(desc(BondMarketSnapshot.as_of))
        .limit(1)
    )
    if (
        term.nominal is None
        or snap is None
        or snap.clean_price_percent is None
        or snap.accrued_interest is None
        or not term.lot_size
    ):
        return {"status": "MISSING_MARKET_OR_TERMS", "symbol": symbol}
    cashflows = session.scalars(
        select(BondCashflow)
        .where(
            BondCashflow.instrument_id == instrument.id,
            BondCashflow.cashflow_date >= as_of,
            BondCashflow.cashflow_type.in_(("COUPON", "AMORTIZATION", "REDEMPTION")),
            BondCashflow.amount.is_not(None),
        )
        .order_by(BondCashflow.cashflow_date)
    ).all()
    # Prefer bondization over legacy board rows; one leg per (date, type).
    dedup: dict[tuple[date, str], BondCashflow] = {}
    for cf in cashflows:
        key = (cf.cashflow_date, cf.cashflow_type)
        prior = dedup.get(key)
        if prior is None or cf.source == "MOEX_ISS_BONDIZATION":
            dedup[key] = cf
    legs = [
        BondCashflowLeg(
            cashflow_date=cf.cashflow_date,
            cashflow_type=cf.cashflow_type,
            amount_per_bond=Decimal(cf.amount),
        )
        for cf in sorted(dedup.values(), key=lambda row: (row.cashflow_date, row.cashflow_type))
    ]
    has_future_offer = (
        session.scalar(
            select(func.count())
            .select_from(BondCashflow)
            .where(
                BondCashflow.instrument_id == instrument.id,
                BondCashflow.cashflow_type == "OFFER",
                BondCashflow.cashflow_date >= as_of,
            )
        )
        or 0
    ) > 0
    preview = preview_hold_to_maturity(
        symbol=symbol,
        nominal=Decimal(term.nominal),
        clean_price_percent=Decimal(snap.clean_price_percent),
        nkd_per_bond=Decimal(snap.accrued_interest),
        lots=lots,
        lot_size=int(term.lot_size),
        costs=TransactionCostProfile(cost_bps),
        future_legs=legs,
        ytm_value=Decimal(snap.yield_value) if snap.yield_value is not None else None,
        ytm_source="MOEX_BOARD_YIELD" if snap.yield_value is not None else None,
        has_future_offer=bool(has_future_offer),
    )
    from dataclasses import asdict

    payload = asdict(preview)
    payload["status"] = "READY"
    payload["support_status"] = term.support_status
    payload["tax_model"] = "NOT_MODELED"
    payload["credit_quality_status"] = term.credit_quality_status
    payload["real_portfolio_eligible"] = real_portfolio_eligible(
        BondType(term.bond_type), CreditQualityStatus(term.credit_quality_status)
    )
    payload["disclaimer"] = (
        "Kraken умеет корректно посчитать денежные потоки бумаги — "
        "это не означает, что облигация безопасна. До налогов, без модели расчётов."
    )
    return payload


def _dirty_estimate(term: BondTerm, snap: BondMarketSnapshot | None) -> float | None:
    if (
        term is None
        or term.nominal is None
        or snap is None
        or snap.clean_price_percent is None
        or snap.accrued_interest is None
    ):
        return None
    clean = float(term.nominal) * float(snap.clean_price_percent) / 100.0
    return clean + float(snap.accrued_interest)


def _schema_ready(session: Session) -> bool:
    return bool(session.execute(text("SELECT to_regclass('investment.bond_terms') IS NOT NULL")).scalar_one())


def _not_ready(reason: str) -> dict[str, Any]:
    return {
        "status": "NOT_READY",
        "bond_terms": 0,
        "cashflows": 0,
        "issues": [{"code": reason, "severity": "BLOCKER"}],
        "tax_model_status": "NOT_MODELED",
        "settlement_status": "SETTLEMENT_NOT_MODELED_V0",
        "flags": {
            "BOND_TERMS_READY": "NOT_READY",
            "COUPON_CASHFLOWS_READY": "NOT_READY",
            "REDEMPTION_READY": "NOT_READY",
            "AMORTIZATION_PARTIAL": "NOT_READY",
            "OFFER_POLICY_NOT_READY": "NOT_READY",
            "CREDIT_QUALITY_NOT_READY": "NOT_READY",
            "BOND_HISTORICAL_TOTAL_RETURN": "NOT_READY",
        },
    }
