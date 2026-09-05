"""Application services for the Investment Foundation V0."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Date, cast, desc, func, select, text
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument, Series, SeriesValue
from app.modules.investment.domain.fixed_income import (
    BondSupportStatus,
    BondType,
    CreditQualityStatus,
    real_portfolio_eligible,
)
from app.modules.investment.domain.hurdle import HurdleQuote, KnownAtQuality
from app.modules.investment.infrastructure.models import BondCashflow, BondTerm


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
    """Prefer FACEUNIT over CURRENCYID.

    Live MOEX TQOB/TQCB rows often show CURRENCYID=SUR while FACEUNIT is CNY/USD.
    Face currency decides whether the bond is a RUB vanilla candidate.
    """
    for raw in (face_unit, currency_id):
        if raw is None:
            continue
        text = str(raw).strip().upper()
        if not text:
            continue
        if text in {"SUR", "RUR", "RUB"}:
            return "RUB"
        return text
    return None


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
    reasons: list[str] = []
    resolved = resolve_bond_face_currency(face_unit=face_unit, currency_id=currency_id) or currency
    if resolved != "RUB":
        reasons.append("currency_not_rub")
    if (coupon_type or "").upper() not in {"FIXED", "CONSTANT"}:
        reasons.append("coupon_not_observed_fixed")
    if nominal is None:
        reasons.append("missing_nominal")
    if maturity_date is None:
        reasons.append("missing_maturity")
    if resolved and resolved != "RUB":
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
    missing_nominal = int(
        session.scalar(
            select(func.count()).select_from(BondTerm).where(BondTerm.nominal.is_(None))
        )
        or 0
    )
    issues = []
    if not terms:
        issues.append({"code": "no_bond_terms", "severity": "BLOCKER"})
    if not cashflows:
        issues.append({"code": "no_observed_cashflows", "severity": "WARNING"})
    if missing_nominal:
        issues.append(
            {"code": "missing_nominal", "severity": "BLOCKER", "count": missing_nominal}
        )
    return {
        "status": "READY" if not any(i["severity"] == "BLOCKER" for i in issues) else "NOT_READY",
        "bond_terms": terms,
        "cashflows": cashflows,
        "issues": issues,
        "tax_model_status": "NOT_MODELED",
        "settlement_status": "SETTLEMENT_NOT_MODELED_V0",
    }


def investment_readiness(session: Session) -> dict[str, Any]:
    hurdle_ready = CbrHurdleProvider(session).quote(date.today()) is not None
    fixed_income = fixed_income_readiness(session)
    checks = [
        {"code": "CBR_HURDLE_READY", "status": "READY" if hurdle_ready else "NOT_READY"},
        {"code": "FIXED_INCOME_DATA_READY", "status": fixed_income["status"]},
        {
            "code": "BOND_CASHFLOWS_READY",
            "status": "READY" if int(fixed_income.get("cashflows") or 0) > 0 else "NOT_READY",
        },
        {"code": "REALISTIC_LOTS_READY", "status": "READY"},
        {"code": "TRANSACTION_COSTS_READY", "status": "READY"},
        {"code": "ASSET_ALLOCATION_RESEARCH_READY", "status": "READY"},
        {"code": "TAX_MODEL_NOT_READY", "status": "NOT_READY"},
        {"code": "CREDIT_QUALITY_NOT_READY", "status": "NOT_READY"},
        {"code": "DIVIDEND_TOTAL_RETURN_NOT_READY", "status": "NOT_READY"},
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
    for instrument, term in rows:
        bond_type = BondType(term.bond_type)
        credit = CreditQualityStatus(term.credit_quality_status)
        result.append(
            {
                "instrument_id": instrument.id,
                "symbol": instrument.symbol,
                "name": instrument.name,
                "currency": instrument.currency,
                "bond_type": bond_type.value,
                "nominal": float(term.nominal) if term.nominal is not None else None,
                "maturity_date": term.maturity_date,
                "support_status": term.support_status,
                "credit_quality_status": credit.value,
                "real_portfolio_eligible": real_portfolio_eligible(bond_type, credit),
            }
        )
    return result


def _schema_ready(session: Session) -> bool:
    return bool(
        session.execute(text("SELECT to_regclass('investment.bond_terms') IS NOT NULL")).scalar_one()
    )


def _not_ready(reason: str) -> dict[str, Any]:
    return {
        "status": "NOT_READY",
        "bond_terms": 0,
        "cashflows": 0,
        "issues": [{"code": reason, "severity": "BLOCKER"}],
        "tax_model_status": "NOT_MODELED",
        "settlement_status": "SETTLEMENT_NOT_MODELED_V0",
    }
