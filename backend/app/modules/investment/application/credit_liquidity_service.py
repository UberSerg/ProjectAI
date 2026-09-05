"""Credit quality & liquidity application services (read-only assessments)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument
from app.modules.investment.domain.credit_quality import (
    CreditQualityAssessment,
    CreditStatus,
    IssuerCreditProfile,
    assess_credit_from_observed,
)
from app.modules.investment.domain.investment_eligibility import (
    EligibilityStatus,
    InvestmentEligibilityAssessment,
    assess_investment_eligibility,
)
from app.modules.investment.domain.liquidity import (
    LiquidityAssessment,
    LiquidityStatus,
    assess_liquidity,
)
from app.modules.investment.infrastructure.models import BondMarketSnapshot, BondTerm

SOURCE_AUDIT: dict[str, Any] = {
    "generated_for": "credit-quality-liquidity-v0",
    "sources": [
        {
            "source": "MOEX_ISS_securities",
            "coverage": "Bond terms / face / coupon observed fields for TQOB/TQCB sample",
            "history": "Point snapshots via ingest — not a rating history store",
            "automation": "ingest_bounded_rub_bonds (scheduler OFF)",
            "timestamp_quality": "as_of / known_at date-only for market snapshots",
            "limitations": [
                "Licensed agency ratings are not present in the free securities columns used by V0",
                "marketdata VALTODAY/NUMTRADES not mapped into typed BondMarketSnapshot columns yet",
            ],
            "access_status": "AVAILABLE_PARTIAL",
        },
        {
            "source": "MOEX_ISS_marketdata",
            "coverage": "Price/yield fields partially mapped (PREVPRICE, YIELD, ACCRUEDINT)",
            "history": "Latest snapshot per ingest as_of",
            "automation": "Same bounded ingest",
            "timestamp_quality": "DATE_ONLY as_of",
            "limitations": [
                "Volume/trade_count not persisted in investment.bond_market_snapshots",
                "Spread not observed → must remain None",
            ],
            "access_status": "AVAILABLE_PARTIAL",
        },
        {
            "source": "CBR",
            "coverage": "KEY_RATE hurdle — not bond issuer credit ratings",
            "history": "Series values in market.series_values",
            "automation": "Existing CBR ingest",
            "timestamp_quality": "DATE_ONLY / series timestamp",
            "limitations": ["CBR key rate is not a corporate credit rating"],
            "access_status": "AVAILABLE_NOT_APPLICABLE_FOR_CREDIT",
        },
        {
            "source": "fundamentals.issuers.metadata",
            "coverage": "MOEX emitent identity (inn/okpo/title) — no rating columns",
            "history": "Identity upsert only",
            "automation": "Fundamentals identity pipeline",
            "timestamp_quality": "updated_at on issuer row",
            "limitations": ["No agency rating fields stored today"],
            "access_status": "AVAILABLE_NO_RATINGS",
        },
        {
            "source": "ACRA_EXPERT_RA_NCR_paid_feeds",
            "coverage": "Would provide agency ratings with scale/date",
            "history": "Vendor-dependent",
            "automation": "Not integrated",
            "timestamp_quality": "Vendor known_at required",
            "limitations": ["Paid subscription / licensing / credentials"],
            "access_status": "READY_REQUIRES_ACCESS",
        },
        {
            "source": "market.candles",
            "coverage": "OHLCV for instruments that have candle history (liquidity proxy)",
            "history": "Daily candles when ingested",
            "automation": "Market data pipelines",
            "timestamp_quality": "candle timestamp",
            "limitations": ["Bonds may lack candle history; volume is a proxy not full order-book liquidity"],
            "access_status": "AVAILABLE_PARTIAL",
        },
    ],
    "principle": "Do not bypass paid rating access. Unknown rating ≠ safe.",
}


def write_source_audit(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(SOURCE_AUDIT, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def assess_instrument(
    session: Session,
    *,
    instrument_id: int,
    as_of: date | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument_id))
    if term is None:
        raise KeyError(f"No BondTerm for instrument_id={instrument_id}")

    credit = assess_credit_from_observed(
        instrument_id=instrument_id,
        issuer_id=None,
        bond_type=term.bond_type,
        stored_credit_status=term.credit_quality_status,
        raw_fields=term.raw_fields or {},
        as_of=as_of,
    )
    liquidity = _liquidity_for_instrument(session, instrument_id=instrument_id, as_of=as_of)
    eligibility = assess_investment_eligibility(
        instrument_id=instrument_id,
        support_status=term.support_status,
        credit=credit,
        liquidity=liquidity,
        bond_type=term.bond_type,
    )
    issuer = IssuerCreditProfile(
        issuer_id=None,
        rating_summary=None,
        sector=None,
        credit_quality_status=credit.credit_status,
        source=credit.source,
        updated_at=datetime.utcnow(),
        limitations=credit.limitations,
    )
    return {
        "instrument_id": instrument_id,
        "bond_type": term.bond_type,
        "support_status": term.support_status,
        "accounting_quality": "YES" if term.support_status == "SUPPORTED" else "NO",
        "credit": _credit_payload(credit),
        "issuer_credit_profile": asdict(issuer) | {"credit_quality_status": credit.credit_status.value},
        "liquidity": _liquidity_payload(liquidity),
        "eligibility": _eligibility_payload(eligibility),
        "risk_flags": list(eligibility.risk_flags),
    }


def list_bond_risk_assessments(session: Session, *, limit: int = 100) -> dict[str, Any]:
    as_of = date.today()
    rows = session.execute(
        select(Instrument, BondTerm)
        .join(BondTerm, BondTerm.instrument_id == Instrument.id)
        .where(Instrument.asset_class == "bond")
        .order_by(Instrument.symbol)
        .limit(limit)
    ).all()

    items = []
    credit_counts = {s.value: 0 for s in CreditStatus}
    liq_counts = {s.value: 0 for s in LiquidityStatus}
    elig_counts = {s.value: 0 for s in EligibilityStatus}

    for instrument, term in rows:
        credit = assess_credit_from_observed(
            instrument_id=instrument.id,
            issuer_id=None,
            bond_type=term.bond_type,
            stored_credit_status=term.credit_quality_status,
            raw_fields=term.raw_fields or {},
            as_of=as_of,
        )
        liquidity = _liquidity_for_instrument(session, instrument_id=instrument.id, as_of=as_of)
        eligibility = assess_investment_eligibility(
            instrument_id=instrument.id,
            support_status=term.support_status,
            credit=credit,
            liquidity=liquidity,
            bond_type=term.bond_type,
        )
        credit_counts[credit.credit_status.value] += 1
        liq_counts[liquidity.liquidity_status.value] += 1
        elig_counts[eligibility.status.value] += 1
        items.append(
            {
                "instrument_id": instrument.id,
                "symbol": instrument.symbol,
                "name": instrument.name,
                "bond_type": term.bond_type,
                "support_status": term.support_status,
                "accounting_quality": "YES" if term.support_status == "SUPPORTED" else "NO",
                "credit_status": credit.credit_status.value,
                "liquidity_status": liquidity.liquidity_status.value,
                "investment_eligibility": eligibility.status.value,
                "eligible": eligibility.eligible,
                "risk_flags": list(eligibility.risk_flags),
                "warnings": list(eligibility.warnings),
                "credit": _credit_payload(credit),
                "liquidity": _liquidity_payload(liquidity),
                "yield_hint": float(term.coupon_rate) / 100
                if term.coupon_rate is not None and term.coupon_rate > 1
                else (float(term.coupon_rate) if term.coupon_rate is not None else None),
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "total_bonds": len(items),
        "credit_coverage": credit_counts,
        "liquidity_coverage": liq_counts,
        "eligibility_coverage": elig_counts,
        "items": items,
        "note": "yield ≠ opportunity; credit + liquidity + data quality required",
        "source_audit": SOURCE_AUDIT,
    }


def aggregate_fixed_income_risk(session: Session) -> dict[str, Any]:
    report = list_bond_risk_assessments(session)
    unknown_credit = report["credit_coverage"].get("UNKNOWN", 0) + report["credit_coverage"].get(
        "NOT_RATED", 0
    )
    low_liq = report["liquidity_coverage"].get("LOW", 0)
    warnings = []
    if unknown_credit:
        warnings.append(
            f"{unknown_credit} облигаций с неизвестным / отсутствующим кредитным качеством."
        )
    if low_liq:
        warnings.append(f"{low_liq} инструментов с низкой ликвидностью требуют проверки.")
    return {
        **report,
        "summary_ru": (
            "Облигационная часть доступна для research, "
            "но часть инструментов имеет неизвестное кредитное качество."
            if unknown_credit
            else "Кредитное покрытие ограничено; рейтинги агентств не подключены без доступа."
        ),
        "allocation_warnings": warnings,
    }


def _liquidity_for_instrument(
    session: Session, *, instrument_id: int, as_of: date
) -> LiquidityAssessment:
    snap = session.scalar(
        select(BondMarketSnapshot)
        .where(BondMarketSnapshot.instrument_id == instrument_id)
        .order_by(desc(BondMarketSnapshot.as_of))
        .limit(1)
    )
    candle = session.scalar(
        select(Candle)
        .where(Candle.instrument_id == instrument_id, Candle.timeframe == "1d")
        .order_by(desc(Candle.timestamp))
        .limit(1)
    )
    last_trade = None
    volume = None
    turnover = None
    trade_count = None
    source = "NONE"

    if snap is not None:
        last_trade = snap.as_of
        source = "investment.bond_market_snapshots"
        obs = snap.observed_fields or {}
        # Only use observed volume/trades if present — never invent.
        for key in ("VALTODAY", "VOLUME", "VOLTODAY"):
            if obs.get(key) not in (None, ""):
                try:
                    volume = float(obs[key])
                except (TypeError, ValueError):
                    pass
                break
        for key in ("NUMTRADES", "TRADES"):
            if obs.get(key) not in (None, ""):
                try:
                    trade_count = int(float(obs[key]))
                except (TypeError, ValueError):
                    pass
                break

    if candle is not None:
        candle_day = candle.timestamp.date() if hasattr(candle.timestamp, "date") else None
        if last_trade is None or (candle_day and candle_day > last_trade):
            last_trade = candle_day
        if volume is None and candle.volume is not None:
            volume = float(candle.volume)
        source = (
            "bond_snapshot+candles"
            if snap is not None
            else "market.candles"
        )

    return assess_liquidity(
        instrument_id=instrument_id,
        as_of=as_of,
        last_trade_date=last_trade,
        volume=volume,
        turnover=turnover,
        trade_count=trade_count,
        spread=None,
        source=source,
    )


def _credit_payload(credit: CreditQualityAssessment) -> dict[str, Any]:
    payload = asdict(credit)
    payload["credit_status"] = credit.credit_status.value
    if isinstance(credit.rating_known_at, datetime):
        payload["rating_known_at"] = credit.rating_known_at.isoformat()
    elif isinstance(credit.rating_known_at, date):
        payload["rating_known_at"] = credit.rating_known_at.isoformat()
    if credit.rating_date is not None:
        payload["rating_date"] = credit.rating_date.isoformat()
    return payload


def _liquidity_payload(liq: LiquidityAssessment) -> dict[str, Any]:
    payload = asdict(liq)
    payload["liquidity_status"] = liq.liquidity_status.value
    if liq.last_trade_date is not None:
        payload["last_trade_date"] = liq.last_trade_date.isoformat()
    return payload


def _eligibility_payload(el: InvestmentEligibilityAssessment) -> dict[str, Any]:
    payload = asdict(el)
    payload["status"] = el.status.value
    return payload
