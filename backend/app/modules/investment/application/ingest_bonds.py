"""Bounded non-production MOEX fixed-income ingest with bondization cashflows.

Scheduler stays OFF. Only observed ISS fields are persisted — no guessed coupons.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument, InstrumentSource
from app.modules.investment.domain.cashflows import (
    MOEX_BONDIZATION_KNOWN_AT_QUALITY,
    classify_bond_support_v1,
    coupon_structure_fixed,
    future_offers,
    has_complex_amortization,
    parse_bondization_schedule,
    remaining_coupons,
)
from app.modules.investment.domain.currency import resolve_nominal_currency
from app.modules.investment.domain.fixed_income import BondCashflowType, BondType, CreditQualityStatus
from app.modules.investment.infrastructure.models import (
    BondCashflow,
    BondMarketSnapshot,
    BondTerm,
)
from app.modules.investment.infrastructure.moex_bonds import (
    SOURCE_BOARD,
    SOURCE_BONDIZATION,
    MoexBondClient,
)


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


def ingest_bounded_rub_bonds(
    session: Session,
    *,
    client: MoexBondClient | None = None,
    per_board: int = 10,
    as_of: date | None = None,
    board_scan_limit: int = 80,
) -> dict[str, Any]:
    """Ingest a small RUB-face cohort with bondization cashflows into investment.*."""
    owns_client = client is None
    client = client or MoexBondClient(auto_close=False)
    as_of = as_of or date.today()
    known_at = as_of

    try:
        selected = _select_rub_candidates(client, per_board=per_board, board_scan_limit=board_scan_limit)
        inserted_instruments = 0
        inserted_terms = 0
        updated_terms = 0
        inserted_snapshots = 0
        cashflow_counts = {
            "COUPON": 0,
            "AMORTIZATION": 0,
            "REDEMPTION": 0,
            "OFFER": 0,
        }
        classified: list[dict[str, Any]] = []
        support_counts = {"SUPPORTED": 0, "RESEARCH_ONLY": 0, "UNSUPPORTED": 0}
        reason_counts: dict[str, int] = {}

        for row in selected:
            secid = str(row.get("SECID") or "").strip()
            if not secid:
                continue
            board = str(row.get("_board") or "")
            face = row["_face"]
            nominal = _decimal(row.get("FACEVALUE"))
            maturity = _date(row.get("MATDATE"))
            lot_size = int(row["LOTSIZE"]) if row.get("LOTSIZE") not in (None, "") else None
            clean = _decimal(row.get("PREVPRICE") or row.get("PRICE") or row.get("LCURRENTPRICE"))
            nkd = _decimal(row.get("ACCRUEDINT"))
            ytm = _decimal(row.get("YIELD"))
            duration = _decimal(row.get("DURATION"))

            bondization = client.fetch_bondization(secid)
            schedule = parse_bondization_schedule(
                coupons=bondization["coupons"],
                amortizations=bondization["amortizations"],
                offers=bondization["offers"],
            )
            support, reasons = classify_bond_support_v1(
                face_unit=row.get("FACEUNIT"),
                currency_id=row.get("CURRENCYID"),
                nominal=float(nominal) if nominal is not None else None,
                lot_size=lot_size,
                maturity_date=maturity,
                schedule=schedule,
                market_price_percent=float(clean) if clean is not None else None,
                as_of=as_of,
            )
            support_counts[support.value] = support_counts.get(support.value, 0) + 1
            for code in reasons:
                reason_counts[code] = reason_counts.get(code, 0) + 1

            coupon_type = "FIXED" if coupon_structure_fixed(schedule, as_of=as_of) else None
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
                        source=SOURCE_BOARD,
                        external_id=secid,
                        board=board,
                        source_metadata={
                            "FACEUNIT": row.get("FACEUNIT"),
                            "CURRENCYID": row.get("CURRENCYID"),
                        },
                    )
                )
                inserted_instruments += 1
            else:
                instrument.currency = face.canonical
                instrument.asset_class = "bond"

            next_coupon = remaining_coupons(schedule, as_of)
            next_c = next_coupon[0] if next_coupon else None
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
                "bondization_known_at_quality": MOEX_BONDIZATION_KNOWN_AT_QUALITY.value,
                "coupon_count": len(schedule.coupons),
                "amortization_count": len(schedule.amortizations),
                "offer_count": len(schedule.offers),
                "future_offer_count": len(future_offers(schedule, as_of)),
                "complex_amortization": has_complex_amortization(schedule),
                "next_coupon_date": next_c.coupon_date.isoformat() if next_c else None,
                "next_coupon_amount": float(next_c.amount) if next_c and next_c.amount is not None else None,
                "duration": float(duration) if duration is not None else None,
                "moex_yield": float(ytm) if ytm is not None else None,
                "accounting_support": support.value == "SUPPORTED",
                "credit_note": (
                    "Cashflow accounting support is not investment safety. "
                    "Corporate credit_quality remains UNKNOWN without a rating source."
                ),
            }

            term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument.id))
            if term is None:
                term = BondTerm(
                    instrument_id=instrument.id,
                    bond_type=bond_type.value,
                    nominal=nominal,
                    currency=face.canonical,
                    coupon_type=coupon_type,
                    coupon_rate=_decimal(row.get("COUPONPERCENT")) or (next_c.rate_percent if next_c else None),
                    maturity_date=maturity,
                    lot_size=lot_size,
                    support_status=support.value,
                    credit_quality_status=CreditQualityStatus.UNKNOWN.value,
                    known_at=known_at,
                    source=SOURCE_BONDIZATION,
                    raw_fields=raw_fields,
                )
                session.add(term)
                inserted_terms += 1
            else:
                term.bond_type = bond_type.value
                term.nominal = nominal
                term.currency = face.canonical
                term.coupon_type = coupon_type
                term.coupon_rate = _decimal(row.get("COUPONPERCENT")) or (next_c.rate_percent if next_c else None)
                term.maturity_date = maturity
                term.lot_size = lot_size
                term.support_status = support.value
                term.raw_fields = raw_fields
                term.known_at = known_at
                term.source = SOURCE_BONDIZATION
                updated_terms += 1

            session.flush()

            existing_snap = session.scalar(
                select(BondMarketSnapshot).where(
                    BondMarketSnapshot.instrument_id == instrument.id,
                    BondMarketSnapshot.as_of == as_of,
                    BondMarketSnapshot.source == SOURCE_BOARD,
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
                        source=SOURCE_BOARD,
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
            else:
                existing_snap.clean_price_percent = clean
                existing_snap.accrued_interest = nkd
                existing_snap.yield_value = ytm

            cf_added = _persist_schedule_cashflows(
                session,
                instrument_id=instrument.id,
                schedule=schedule,
                face_currency=face.canonical,
                known_at=known_at,
                maturity=maturity,
                nominal=nominal,
            )
            for key, value in cf_added.items():
                cashflow_counts[key] = cashflow_counts.get(key, 0) + value

            classified.append(
                {
                    "secid": secid,
                    "board": board,
                    "bond_type": bond_type.value,
                    "FACEUNIT": row.get("FACEUNIT"),
                    "canonical_currency": face.canonical,
                    "currency_display": face.display_ru,
                    "support_status": support.value,
                    "reasons": reasons,
                    "next_coupon_date": raw_fields["next_coupon_date"],
                    "next_coupon_amount": raw_fields["next_coupon_amount"],
                    "maturity_date": maturity.isoformat() if maturity else None,
                    "nominal": float(nominal) if nominal is not None else None,
                    "lot_size": lot_size,
                    "nkd": float(nkd) if nkd is not None else None,
                    "clean_price_percent": float(clean) if clean is not None else None,
                    "moex_yield": float(ytm) if ytm is not None else None,
                }
            )

        session.flush()
        return {
            "as_of": as_of.isoformat(),
            "generated_at": datetime.now(UTC).isoformat(),
            "selected": len(selected),
            "inserted_instruments": inserted_instruments,
            "inserted_terms": inserted_terms,
            "updated_terms": updated_terms,
            "inserted_snapshots": inserted_snapshots,
            "cashflow_counts": cashflow_counts,
            "support_counts": support_counts,
            "reason_counts": reason_counts,
            "classified": classified,
            "known_at_quality": MOEX_BONDIZATION_KNOWN_AT_QUALITY.value,
            "note": (
                "Bondization schedule is CURRENT_STATE_ONLY. "
                "No coupon amounts were guessed. Offers never auto-close positions."
            ),
        }
    finally:
        if owns_client:
            client.close()


def _select_rub_candidates(
    client: MoexBondClient,
    *,
    per_board: int,
    board_scan_limit: int,
) -> list[dict[str, Any]]:
    """Prefer RUB bonds with observed coupon value and without board offer date."""
    selected: list[dict[str, Any]] = []
    for board in ("TQOB", "TQCB"):
        rows = client.fetch_board_rows(board, limit=board_scan_limit)
        rub_rows: list[dict[str, Any]] = []
        for row in rows:
            face = resolve_nominal_currency(face_unit=row.get("FACEUNIT"), currency_id=row.get("CURRENCYID"))
            if face.canonical != "RUB":
                continue
            if _date(row.get("MATDATE")) is None:
                continue
            if _decimal(row.get("FACEVALUE")) is None:
                continue
            rub_rows.append({**row, "_board": board, "_face": face})

        def _rank(item: dict[str, Any]) -> tuple[int, int, str]:
            has_offer = 0 if _date(item.get("OFFERDATE")) is None else 1
            has_coupon_value = 0 if item.get("COUPONVALUE") not in (None, "") else 1
            return (has_offer, has_coupon_value, str(item.get("SECID") or ""))

        rub_rows.sort(key=_rank)
        selected.extend(rub_rows[:per_board])
    return selected


def _persist_schedule_cashflows(
    session: Session,
    *,
    instrument_id: int,
    schedule,
    face_currency: str,
    known_at: date,
    maturity: date | None,
    nominal: Decimal | None,
) -> dict[str, int]:
    added = {"COUPON": 0, "AMORTIZATION": 0, "REDEMPTION": 0, "OFFER": 0}

    for coupon in schedule.coupons:
        if coupon.amount is None:
            continue
        if _upsert_cashflow(
            session,
            instrument_id=instrument_id,
            cashflow_date=coupon.coupon_date,
            cashflow_type=BondCashflowType.COUPON.value,
            amount=coupon.amount,
            currency=coupon.currency or face_currency,
            known_at=known_at,
            raw_fields={
                **coupon.raw,
                "known_at_quality": MOEX_BONDIZATION_KNOWN_AT_QUALITY.value,
                "coupon_rate_percent": float(coupon.rate_percent) if coupon.rate_percent is not None else None,
                "nominal_base": float(coupon.face_value) if coupon.face_value is not None else None,
                "source_endpoint": "/iss/securities/{secid}/bondization.json#coupons",
            },
        ):
            added["COUPON"] += 1

    redemption_dates: set[date] = set()
    for amort in schedule.amortizations:
        if amort.amount is None:
            continue
        is_maturity = (amort.data_source or "").lower() == "maturity" or (
            maturity is not None and amort.amort_date == maturity
        )
        cf_type = BondCashflowType.REDEMPTION.value if is_maturity else BondCashflowType.AMORTIZATION.value
        if _upsert_cashflow(
            session,
            instrument_id=instrument_id,
            cashflow_date=amort.amort_date,
            cashflow_type=cf_type,
            amount=amort.amount,
            currency=amort.currency or face_currency,
            known_at=known_at,
            raw_fields={
                **amort.raw,
                "known_at_quality": MOEX_BONDIZATION_KNOWN_AT_QUALITY.value,
                "source_endpoint": "/iss/securities/{secid}/bondization.json#amortizations",
            },
        ):
            added[cf_type] += 1
        if cf_type == BondCashflowType.REDEMPTION.value:
            redemption_dates.add(amort.amort_date)
            # Drop legacy board-only redemption duplicates for the same date.
            session.execute(
                delete(BondCashflow).where(
                    BondCashflow.instrument_id == instrument_id,
                    BondCashflow.cashflow_date == amort.amort_date,
                    BondCashflow.cashflow_type == BondCashflowType.REDEMPTION.value,
                    BondCashflow.source == SOURCE_BOARD,
                )
            )

    if maturity is not None and nominal is not None and maturity not in redemption_dates:
        if _upsert_cashflow(
            session,
            instrument_id=instrument_id,
            cashflow_date=maturity,
            cashflow_type=BondCashflowType.REDEMPTION.value,
            amount=nominal,
            currency=face_currency,
            known_at=known_at,
            raw_fields={
                "MATDATE": maturity.isoformat(),
                "FACEVALUE": float(nominal),
                "known_at_quality": MOEX_BONDIZATION_KNOWN_AT_QUALITY.value,
                "source_endpoint": "board_securities_fallback",
            },
            source=SOURCE_BOARD,
        ):
            added["REDEMPTION"] += 1

    for offer in schedule.offers:
        if _upsert_cashflow(
            session,
            instrument_id=instrument_id,
            cashflow_date=offer.offer_date,
            cashflow_type=BondCashflowType.OFFER.value,
            amount=offer.price,
            currency=face_currency,
            known_at=known_at,
            raw_fields={
                **offer.raw,
                "known_at_quality": MOEX_BONDIZATION_KNOWN_AT_QUALITY.value,
                "auto_exercise": False,
                "source_endpoint": "/iss/securities/{secid}/bondization.json#offers",
            },
        ):
            added["OFFER"] += 1

    return added


def _upsert_cashflow(
    session: Session,
    *,
    instrument_id: int,
    cashflow_date: date,
    cashflow_type: str,
    amount: Decimal | None,
    currency: str | None,
    known_at: date,
    raw_fields: dict[str, Any],
    source: str = SOURCE_BONDIZATION,
) -> bool:
    existing = session.scalar(
        select(BondCashflow).where(
            BondCashflow.instrument_id == instrument_id,
            BondCashflow.cashflow_date == cashflow_date,
            BondCashflow.cashflow_type == cashflow_type,
            BondCashflow.source == source,
        )
    )
    if existing is None:
        session.add(
            BondCashflow(
                instrument_id=instrument_id,
                cashflow_date=cashflow_date,
                cashflow_type=cashflow_type,
                amount=amount,
                currency=currency,
                known_at=known_at,
                source=source,
                raw_fields=raw_fields,
            )
        )
        return True
    existing.amount = amount
    existing.currency = currency
    existing.known_at = known_at
    existing.raw_fields = {
        **(existing.raw_fields or {}),
        **raw_fields,
        "revised_at_ingest": known_at.isoformat(),
    }
    return False
