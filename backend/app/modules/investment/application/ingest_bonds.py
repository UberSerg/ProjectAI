"""Bounded non-production MOEX fixed-income ingest (Docker acceptance only).

Scheduler stays OFF. Only observed ISS fields are persisted — no guessed coupons.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument, InstrumentSource
from app.modules.investment.application.services import classify_vanilla_rub_fixed_rate
from app.modules.investment.domain.currency import resolve_nominal_currency
from app.modules.investment.domain.fixed_income import BondType, CreditQualityStatus
from app.modules.investment.infrastructure.models import (
    BondCashflow,
    BondMarketSnapshot,
    BondTerm,
)
from app.modules.investment.infrastructure.moex_bonds import MoexBondClient

SOURCE = "MOEX_ISS"


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _date(value: Any) -> date | None:
    if value in (None, "", "0000-00-00"):
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _bond_type(board: str, secid: str) -> BondType:
    if board == "TQOB" or str(secid).upper().startswith("SU"):
        return BondType.GOVERNMENT
    return BondType.CORPORATE


def _coupon_type_observed(row: dict[str, Any]) -> str | None:
    # Do not invent FIXED from presence of COUPONPERCENT alone — floater risk.
    explicit = row.get("COUPONTYPE") or row.get("COUPON_TYPE") or row.get("COUPONFREQUENCY")
    if explicit in (None, ""):
        return None
    text = str(explicit).strip().upper()
    if text in {"FIXED", "CONSTANT", "FIX", "ПД", "FIXED_RATE"}:
        return "FIXED"
    return None


def ingest_bounded_rub_bonds(
    session: Session,
    *,
    client: MoexBondClient | None = None,
    per_board: int = 8,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Ingest a small RUB-face cohort from TQOB/TQCB into investment.* tables."""
    client = client or MoexBondClient()
    as_of = as_of or date.today()
    known_at = as_of
    audit = client.audit(limit=max(per_board * 3, 20))
    selected: list[dict[str, Any]] = []
    previously_wrong_sur: list[dict[str, Any]] = []

    for board_block in audit.get("boards") or []:
        board = str(board_block.get("board") or "")
        rub_rows: list[dict[str, Any]] = []
        for row in board_block.get("rows") or []:
            face_unit = row.get("FACEUNIT")
            currency_id = row.get("CURRENCYID")
            face = resolve_nominal_currency(face_unit=face_unit, currency_id=currency_id)
            # Track rows that look like the old false-negative pattern (SUR face).
            if str(face_unit or "").upper() == "SUR":
                previously_wrong_sur.append(
                    {
                        "secid": row.get("SECID"),
                        "board": board,
                        "FACEUNIT": face_unit,
                        "CURRENCYID": currency_id,
                        "canonical_nominal": face.canonical,
                        "new_classification_hint": (
                            "RUB_FACE" if face.canonical == "RUB" else face.canonical
                        ),
                    }
                )
            if face.canonical != "RUB":
                continue
            rub_rows.append({**row, "_board": board, "_face": face})
        selected.extend(rub_rows[:per_board])

    inserted_instruments = 0
    inserted_terms = 0
    inserted_snapshots = 0
    inserted_cashflows = 0
    classified: list[dict[str, Any]] = []

    for row in selected:
        secid = str(row.get("SECID") or "").strip()
        if not secid:
            continue
        board = str(row.get("_board") or "")
        face = row["_face"]
        nominal = _decimal(row.get("FACEVALUE"))
        maturity = _date(row.get("MATDATE"))
        has_offer = _date(row.get("OFFERDATE")) is not None
        coupon_type = _coupon_type_observed(row)
        support, reasons = classify_vanilla_rub_fixed_rate(
            currency=face.canonical,
            coupon_type=coupon_type,
            has_offer=has_offer,
            nominal=float(nominal) if nominal is not None else None,
            maturity_date=maturity,
            face_unit=row.get("FACEUNIT"),
            currency_id=row.get("CURRENCYID"),
        )
        bond_type = _bond_type(board, secid)

        instrument = session.scalar(select(Instrument).where(Instrument.symbol == secid))
        if instrument is None:
            instrument = Instrument(
                symbol=secid,
                name=str(row.get("SECNAME") or row.get("SHORTNAME") or secid),
                asset_class="bond",
                exchange="MOEX",
                currency=face.canonical,
                isin=row.get("ISIN"),
                is_active=True,
            )
            session.add(instrument)
            session.flush()
            session.add(
                InstrumentSource(
                    instrument_id=instrument.id,
                    source=SOURCE,
                    external_id=secid,
                    board=board,
                    source_metadata={"FACEUNIT": row.get("FACEUNIT"), "CURRENCYID": row.get("CURRENCYID")},
                )
            )
            inserted_instruments += 1
        else:
            instrument.currency = face.canonical
            instrument.asset_class = "bond"

        term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument.id))
        raw_fields = {
            "FACEUNIT": row.get("FACEUNIT"),
            "CURRENCYID": row.get("CURRENCYID"),
            "FACEVALUE": row.get("FACEVALUE"),
            "MATDATE": row.get("MATDATE"),
            "OFFERDATE": row.get("OFFERDATE"),
            "COUPONPERCENT": row.get("COUPONPERCENT"),
            "COUPONVALUE": row.get("COUPONVALUE"),
            "LOTSIZE": row.get("LOTSIZE"),
            "BOARDID": row.get("BOARDID") or board,
            "canonical_nominal_currency": face.canonical,
            "currency_raw_faceunit": face.raw_value,
            "support_reasons": reasons,
        }
        if term is None:
            term = BondTerm(
                instrument_id=instrument.id,
                bond_type=bond_type.value,
                nominal=nominal,
                currency=face.canonical,
                coupon_type=coupon_type,
                coupon_rate=_decimal(row.get("COUPONPERCENT")),
                maturity_date=maturity,
                lot_size=int(row["LOTSIZE"]) if row.get("LOTSIZE") not in (None, "") else None,
                support_status=support.value,
                credit_quality_status=CreditQualityStatus.UNKNOWN.value,
                known_at=known_at,
                source=SOURCE,
                raw_fields=raw_fields,
            )
            session.add(term)
            inserted_terms += 1
        else:
            term.bond_type = bond_type.value
            term.nominal = nominal
            term.currency = face.canonical
            term.coupon_type = coupon_type
            term.coupon_rate = _decimal(row.get("COUPONPERCENT"))
            term.maturity_date = maturity
            term.support_status = support.value
            term.raw_fields = raw_fields
            term.known_at = known_at

        session.flush()

        # Market snapshot from observed board fields only.
        clean = _decimal(row.get("PREVPRICE") or row.get("PRICE") or row.get("LCURRENTPRICE"))
        nkd = _decimal(row.get("ACCRUEDINT"))
        ytm = _decimal(row.get("YIELD"))
        existing_snap = session.scalar(
            select(BondMarketSnapshot).where(
                BondMarketSnapshot.instrument_id == instrument.id,
                BondMarketSnapshot.as_of == as_of,
                BondMarketSnapshot.source == SOURCE,
            )
        )
        if existing_snap is None:
            session.add(
                BondMarketSnapshot(
                    instrument_id=instrument.id,
                    as_of=as_of,
                    clean_price_percent=clean,
                    accrued_interest=nkd,
                    yield_value=ytm,
                    source=SOURCE,
                    observed_fields={
                        k: row.get(k)
                        for k in (
                            "PREVPRICE",
                            "ACCRUEDINT",
                            "YIELD",
                            "DURATION",
                            "LOTSIZE",
                            "FACEUNIT",
                            "CURRENCYID",
                        )
                        if k in row
                    },
                )
            )
            inserted_snapshots += 1

        # Cashflows: only when MATDATE + FACEVALUE observed — REDENTION at maturity.
        # Do not invent coupon schedule dates.
        if maturity is not None and nominal is not None:
            existing_cf = session.scalar(
                select(BondCashflow).where(
                    BondCashflow.instrument_id == instrument.id,
                    BondCashflow.cashflow_date == maturity,
                    BondCashflow.cashflow_type == "REDEMPTION",
                    BondCashflow.source == SOURCE,
                )
            )
            if existing_cf is None:
                session.add(
                    BondCashflow(
                        instrument_id=instrument.id,
                        cashflow_date=maturity,
                        cashflow_type="REDEMPTION",
                        amount=nominal,
                        currency=face.canonical,
                        known_at=known_at,
                        source=SOURCE,
                        raw_fields={"MATDATE": row.get("MATDATE"), "FACEVALUE": row.get("FACEVALUE")},
                    )
                )
                inserted_cashflows += 1

        classified.append(
            {
                "secid": secid,
                "board": board,
                "bond_type": bond_type.value,
                "FACEUNIT": row.get("FACEUNIT"),
                "CURRENCYID": row.get("CURRENCYID"),
                "canonical_currency": face.canonical,
                "currency_display": face.display_ru,
                "support_status": support.value,
                "reasons": reasons,
            }
        )

    session.flush()
    return {
        "as_of": as_of.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "selected": len(selected),
        "inserted_instruments": inserted_instruments,
        "inserted_terms": inserted_terms,
        "inserted_snapshots": inserted_snapshots,
        "inserted_cashflows": inserted_cashflows,
        "classified": classified,
        "previously_sur_face_examples": previously_wrong_sur[:12],
        "note": "No coupon schedule invented; only observed maturity redemption cashflow.",
    }
