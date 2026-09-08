"""Bonds Catalog V2 — Instrument Master bonds with optional FI enrichment joins.

Master-only rows are included (LEFT JOIN terms/cashflows/credit). Pagination,
search, and filters are server-side. Opening a missing bond enqueues FI
enrichment once (dedupe via unique job key).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.investment.application.credit_rating_provider import resolve_instrument_credit
from app.modules.investment.domain.cashflows import reason_code_ru
from app.modules.investment.domain.credit_intelligence import (
    CreditAvailabilityStatus,
    is_russian_federal_government_bond,
)
from app.modules.investment.domain.currency import display_currency_ru
from app.modules.investment.infrastructure.models import BondCashflow, BondMarketSnapshot, BondTerm
from app.modules.market.application.instrument_classification import (
    CORPORATE_BOND,
    MUNICIPAL_BOND,
    OFZ_GOV,
)


def bonds_catalog_v2(
    session: Session,
    *,
    page: int = 1,
    page_size: int = 50,
    q: str | None = None,
    subtype: str | None = None,
    active: bool | None = None,
    valuation_available: bool | None = None,
    cashflow_available: bool | None = None,
    credit_available: bool | None = None,
    support_level: str | None = None,
) -> dict[str, Any]:
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))
    offset = (page - 1) * page_size

    cf_exists = (
        select(BondCashflow.instrument_id)
        .where(BondCashflow.instrument_id == Instrument.id)
        .exists()
    )
    term_exists = (
        select(BondTerm.instrument_id).where(BondTerm.instrument_id == Instrument.id).exists()
    )

    base = (
        select(Instrument, BondTerm)
        .outerjoin(BondTerm, BondTerm.instrument_id == Instrument.id)
        .where(func.lower(Instrument.asset_class) == "bond")
    )

    if q:
        needle = f"%{q.strip()}%"
        # Issuer title via mapping when available
        try:
            from app.modules.fundamentals.infrastructure.models import Issuer, SecurityIssuerMapping

            issuer_title = (
                select(Issuer.title)
                .select_from(SecurityIssuerMapping)
                .join(Issuer, Issuer.id == SecurityIssuerMapping.issuer_id)
                .where(SecurityIssuerMapping.instrument_id == Instrument.id)
                .correlate(Instrument)
                .scalar_subquery()
            )
            base = base.where(
                or_(
                    Instrument.symbol.ilike(needle),
                    Instrument.name.ilike(needle),
                    issuer_title.ilike(needle),
                )
            )
        except Exception:  # noqa: BLE001
            base = base.where(
                or_(Instrument.symbol.ilike(needle), Instrument.name.ilike(needle))
            )

    if subtype:
        st = subtype.strip().lower()
        if st in {OFZ_GOV, "ofz", "government"}:
            base = base.where(
                or_(
                    func.lower(Instrument.instrument_subtype) == OFZ_GOV,
                    BondTerm.bond_type == "Government",
                )
            )
        elif st in {CORPORATE_BOND, "corporate"}:
            base = base.where(
                or_(
                    func.lower(Instrument.instrument_subtype) == CORPORATE_BOND,
                    BondTerm.bond_type == "Corporate",
                )
            )
        elif st in {MUNICIPAL_BOND, "municipal"}:
            base = base.where(
                or_(
                    func.lower(Instrument.instrument_subtype) == MUNICIPAL_BOND,
                    BondTerm.bond_type == "Municipal",
                )
            )
        else:
            base = base.where(func.lower(Instrument.instrument_subtype) == st)

    if active is not None:
        base = base.where(Instrument.is_active.is_(bool(active)))

    if support_level:
        base = base.where(func.upper(Instrument.support_level) == support_level.strip().upper())

    if valuation_available is True:
        base = base.where(and_(term_exists, BondTerm.nominal.is_not(None)))
    elif valuation_available is False:
        base = base.where(~term_exists)

    if cashflow_available is True:
        base = base.where(cf_exists)
    elif cashflow_available is False:
        base = base.where(~cf_exists)

    # Credit filter uses availability after row materialization for honesty with NOT_READY;
    # pre-filter government / current when possible.
    count_q = select(func.count()).select_from(base.order_by(None).subquery())
    total = int(session.scalar(count_q) or 0)

    rows = session.execute(
        base.order_by(Instrument.symbol).offset(offset).limit(page_size)
    ).all()

    items: list[dict[str, Any]] = []
    summary = {
        "active": 0,
        "valuation_ready": 0,
        "cashflow_ready": 0,
        "credit_ready": 0,
        "ofz": 0,
        "corporate": 0,
        "government_debt": 0,
        "source_not_ready": 0,
    }

    # Global summary (cheap aggregates, not page-scoped)
    summary.update(_catalog_summary(session))

    for instrument, term in rows:
        item = _catalog_row(session, instrument, term)
        if credit_available is True and not (
            item.get("credit_available") or item.get("is_government_debt")
        ):
            continue
        if credit_available is False and (
            item.get("credit_available") or item.get("is_government_debt")
        ):
            continue
        items.append(item)

    # If credit filter dropped rows, recount is approximate; prefer honest page from master.
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "summary": summary,
        "filters_applied": {
            "q": q,
            "subtype": subtype,
            "active": active,
            "valuation_available": valuation_available,
            "cashflow_available": cashflow_available,
            "credit_available": credit_available,
            "support_level": support_level,
        },
        "catalog_version": "bonds_v2",
    }


def _catalog_summary(session: Session) -> dict[str, int]:
    bonds = select(Instrument).where(func.lower(Instrument.asset_class) == "bond")
    active = int(
        session.scalar(select(func.count()).select_from(bonds.where(Instrument.is_active.is_(True)).subquery()))
        or session.scalar(
            select(func.count())
            .select_from(Instrument)
            .where(Instrument.asset_class == "bond", Instrument.is_active.is_(True))
        )
        or 0
    )
    valuation_ready = int(
        session.scalar(
            select(func.count())
            .select_from(BondTerm)
            .where(BondTerm.nominal.is_not(None))
        )
        or 0
    )
    cashflow_ready = int(
        session.scalar(select(func.count(func.distinct(BondCashflow.instrument_id)))) or 0
    )
    ofz = int(
        session.scalar(
            select(func.count())
            .select_from(Instrument)
            .where(
                Instrument.asset_class == "bond",
                or_(
                    func.lower(Instrument.instrument_subtype) == OFZ_GOV,
                    Instrument.instrument_subtype == "ofz_gov",
                ),
            )
        )
        or 0
    )
    # Prefer BondTerm Government count when subtype sparse
    ofz_terms = int(
        session.scalar(
            select(func.count()).select_from(BondTerm).where(BondTerm.bond_type == "Government")
        )
        or 0
    )
    corporate = int(
        session.scalar(
            select(func.count()).select_from(BondTerm).where(BondTerm.bond_type == "Corporate")
        )
        or 0
    )
    return {
        "active": active,
        "valuation_ready": valuation_ready,
        "cashflow_ready": cashflow_ready,
        "credit_ready": 0,  # honest until provider stores CURRENT_RATING_AVAILABLE
        "ofz": max(ofz, ofz_terms),
        "corporate": corporate,
        "government_debt": max(ofz, ofz_terms),
        "source_not_ready": corporate,  # corporates lack ratings while provider NOT_READY
    }


def _catalog_row(session: Session, instrument: Instrument, term: BondTerm | None) -> dict[str, Any]:
    bond_type = term.bond_type if term else None
    subtype = getattr(instrument, "instrument_subtype", None)
    credit = resolve_instrument_credit(
        session,
        instrument_id=int(instrument.id),
        symbol=str(instrument.symbol),
        bond_type=bond_type,
        subtype=subtype,
    )
    cf_count = int(
        session.scalar(
            select(func.count())
            .select_from(BondCashflow)
            .where(BondCashflow.instrument_id == instrument.id)
        )
        or 0
    )
    snap = session.scalar(
        select(BondMarketSnapshot)
        .where(BondMarketSnapshot.instrument_id == instrument.id)
        .order_by(BondMarketSnapshot.as_of.desc())
        .limit(1)
    )
    reasons = list((term.raw_fields or {}).get("support_reasons") or []) if term else []
    valuation_ok = term is not None and term.nominal is not None
    return {
        "instrument_id": instrument.id,
        "symbol": instrument.symbol,
        "name": instrument.name,
        "is_active": bool(instrument.is_active),
        "support_level": instrument.support_level,
        "instrument_subtype": subtype,
        "currency": (term.currency if term else None) or instrument.currency,
        "currency_display": display_currency_ru(
            (term.currency if term else None) or instrument.currency or "UNKNOWN"
        ),
        "bond_type": bond_type,
        "nominal": float(term.nominal) if term and term.nominal is not None else None,
        "lot_size": term.lot_size if term else None,
        "maturity_date": term.maturity_date.isoformat() if term and term.maturity_date else None,
        "support_status": term.support_status if term else "UNSUPPORTED",
        "valuation_available": valuation_ok,
        "cashflow_available": cf_count > 0,
        "cashflow_count": cf_count,
        "market_snapshot_available": snap is not None,
        "clean_price_percent": (
            float(snap.clean_price_percent) if snap and snap.clean_price_percent is not None else None
        ),
        "credit_available": bool(credit.get("credit_available")),
        "is_government_debt": bool(credit.get("is_government_debt")),
        "availability_status": credit.get("availability_status"),
        "credit_status": credit.get("credit_status"),
        "risk_flags": credit.get("risk_flags") or [],
        "badges": _badges(valuation_ok, cf_count > 0, credit),
        "enrichment_pending": term is None,
        "support_reasons": reasons,
        "support_reasons_ru": [reason_code_ru(code) for code in reasons],
        "master_only": term is None,
    }


def _badges(valuation_ok: bool, cashflow_ok: bool, credit: dict[str, Any]) -> list[dict[str, str]]:
    badges: list[dict[str, str]] = []
    badges.append(
        {"id": "price", "label": "Цена", "state": "ready" if valuation_ok else "missing"}
    )
    badges.append(
        {"id": "cashflow", "label": "Выплаты", "state": "ready" if cashflow_ok else "missing"}
    )
    if credit.get("is_government_debt"):
        badges.append({"id": "government", "label": "Государственный долг", "state": "ready"})
    elif credit.get("credit_available"):
        badges.append({"id": "credit", "label": "Кредит", "state": "ready"})
    elif credit.get("availability_status") == CreditAvailabilityStatus.SOURCE_NOT_READY.value:
        badges.append({"id": "credit", "label": "Кредит", "state": "source_not_ready"})
    else:
        badges.append({"id": "credit", "label": "Кредит", "state": "missing"})
    return badges


def get_bond_detail_v2(session: Session, symbol: str) -> dict[str, Any] | None:
    """Bond detail: always 200 for master bond rows (terms optional)."""
    instrument = session.scalar(
        select(Instrument).where(
            func.upper(Instrument.symbol) == symbol.upper(),
            func.lower(Instrument.asset_class) == "bond",
        )
    )
    if instrument is None:
        return None
    term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument.id))
    row = _catalog_row(session, instrument, term)
    cashflows = []
    if term is not None:
        cfs = session.scalars(
            select(BondCashflow)
            .where(BondCashflow.instrument_id == instrument.id)
            .order_by(BondCashflow.cashflow_date)
        ).all()
        cashflows = [
            {
                "cashflow_date": cf.cashflow_date.isoformat() if cf.cashflow_date else None,
                "cashflow_type": cf.cashflow_type,
                "amount": float(cf.amount) if cf.amount is not None else None,
                "currency": cf.currency,
                "source": cf.source,
            }
            for cf in cfs
        ]
    return {
        **row,
        "cashflows": cashflows,
        "why_kraken_ru": _why_kraken(row),
        "as_of": date.today().isoformat(),
    }


def _why_kraken(bond: dict[str, Any]) -> str:
    parts = [
        f"Поддержка учёта: {bond.get('support_status') or 'UNSUPPORTED'}.",
        f"Кредитный статус: {bond.get('availability_status') or bond.get('credit_status')}.",
    ]
    if bond.get("master_only"):
        parts.append("Инструмент есть в Instrument Master; terms ещё не обогащены.")
    if bond.get("is_government_debt"):
        parts.append("ОФЗ / госдолг РФ — не корпоративный рейтинг агентства.")
    if bond.get("availability_status") == CreditAvailabilityStatus.SOURCE_NOT_READY.value:
        parts.append(
            "Источник рейтингов недоступен (SOURCE_NOT_READY) — это не «рейтинг не найден»."
        )
    parts.append(
        "Kraken умеет корректно посчитать денежные потоки бумаги — "
        "это не означает, что облигация безопасна."
    )
    return " ".join(parts)


def ensure_fi_enrichment_for_bond(session: Session, symbol: str) -> dict[str, Any]:
    """Enqueue FI enrichment once when opening/adding a master bond (dedupe)."""
    from app.modules.investment.application.enrichment_service import enqueue_enrichment
    from app.modules.investment.domain.enrichment import EnrichmentKind, EnrichmentPriority

    instrument = session.scalar(
        select(Instrument).where(
            func.upper(Instrument.symbol) == symbol.upper(),
            func.lower(Instrument.asset_class) == "bond",
        )
    )
    if instrument is None:
        return {"status": "NOT_FOUND", "symbol": symbol}
    term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument.id))
    if term is not None and term.nominal is not None:
        return {
            "status": "ALREADY_ENRICHED",
            "symbol": symbol,
            "instrument_id": instrument.id,
        }
    jobs = []
    for kind in (
        EnrichmentKind.FIXED_INCOME_TERMS,
        EnrichmentKind.FIXED_INCOME_CASHFLOWS,
        EnrichmentKind.FIXED_INCOME_MARKET,
    ):
        job = enqueue_enrichment(
            session,
            instrument_id=int(instrument.id),
            kind=kind,
            priority=EnrichmentPriority.P1_NEW_BOND,
        )
        jobs.append({"kind": kind.value, "job_id": getattr(job, "id", None), "status": getattr(job, "status", None)})
    return {
        "status": "ENQUEUED",
        "symbol": symbol,
        "instrument_id": instrument.id,
        "jobs": jobs,
        "deduped": True,
    }
