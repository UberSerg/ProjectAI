"""Portfolio credit coverage — value-weighted, no auto trade from ratings."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.investment.application.credit_rating_provider import resolve_instrument_credit
from app.modules.investment.domain.credit_intelligence import CreditAvailabilityStatus
from app.modules.investment.infrastructure.models import BondTerm
from app.modules.market.application.instrument_classification import OFZ_GOV
from app.modules.portfolio.application.manual_portfolio_service import _issuer_key


def build_portfolio_credit_intelligence(
    session: Session,
    *,
    positions: list[dict[str, Any]],
    nav: Decimal | float,
) -> dict[str, Any]:
    """Value-weighted bond credit coverage for manual portfolio analysis.

    Does not invent ratings. OFZ → government_weight.
    rated_corporate_weight stays 0 until CURRENT_RATING_AVAILABLE observations exist.
    Distinguishes SOURCE_NOT_READY vs NO_RATING_FOUND.
    """
    nav_d = Decimal(str(nav)) if nav is not None else Decimal("0")
    gov_mv = Decimal("0")
    corp_mv = Decimal("0")
    rated_corp_mv = Decimal("0")
    unrated_corp_mv = Decimal("0")
    source_not_ready_mv = Decimal("0")
    no_rating_mv = Decimal("0")
    mapping_failed_mv = Decimal("0")
    other_bond_mv = Decimal("0")
    bond_mv_total = Decimal("0")
    issuers: dict[str, dict[str, Any]] = {}

    from sqlalchemy import select

    for row in positions:
        symbol = str(row.get("symbol") or "")
        mv = row.get("market_value")
        if mv is None:
            continue
        mv_d = Decimal(str(mv))
        instrument_id = row.get("instrument_id")
        instrument = session.get(Instrument, instrument_id) if instrument_id else None
        if instrument is None:
            continue
        asset = (instrument.asset_class or "").lower()
        subtype = (instrument.instrument_subtype or "").lower()
        if asset != "bond" and subtype not in {OFZ_GOV, "corporate_bond", "municipal_bond"}:
            continue

        bond_mv_total += mv_d
        term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument.id))
        bond_type = term.bond_type if term else None
        credit = resolve_instrument_credit(
            session,
            instrument_id=int(instrument.id),
            symbol=symbol,
            bond_type=bond_type,
            subtype=subtype,
        )
        avail = credit.get("availability_status")
        ikey, ititle = _issuer_key(session, int(instrument.id), symbol)
        bucket = issuers.setdefault(
            ikey,
            {
                "issuer_key": ikey,
                "issuer_title": ititle,
                "market_value": Decimal("0"),
                "availability_status": avail,
                "rating_raw": credit.get("rating_raw"),
                "agency_code": credit.get("agency_code"),
                "symbols": [],
            },
        )
        bucket["market_value"] = Decimal(str(bucket["market_value"])) + mv_d
        if symbol not in bucket["symbols"]:
            bucket["symbols"].append(symbol)
        # Prefer more informative status if mixed
        if avail == CreditAvailabilityStatus.CURRENT_RATING_AVAILABLE.value:
            bucket["availability_status"] = avail
            bucket["rating_raw"] = credit.get("rating_raw")
            bucket["agency_code"] = credit.get("agency_code")

        if avail == CreditAvailabilityStatus.GOVERNMENT_RUSSIAN_FEDERAL.value or (
            bond_type == "Government" or subtype == OFZ_GOV
        ):
            gov_mv += mv_d
        elif bond_type == "Corporate" or subtype == "corporate_bond":
            corp_mv += mv_d
            if avail == CreditAvailabilityStatus.CURRENT_RATING_AVAILABLE.value:
                rated_corp_mv += mv_d
            elif avail == CreditAvailabilityStatus.SOURCE_NOT_READY.value:
                source_not_ready_mv += mv_d
                unrated_corp_mv += mv_d
            elif avail == CreditAvailabilityStatus.NO_RATING_FOUND.value:
                no_rating_mv += mv_d
                unrated_corp_mv += mv_d
            elif avail == CreditAvailabilityStatus.MAPPING_FAILED.value:
                mapping_failed_mv += mv_d
                unrated_corp_mv += mv_d
            else:
                unrated_corp_mv += mv_d
        else:
            other_bond_mv += mv_d
            if avail == CreditAvailabilityStatus.SOURCE_NOT_READY.value:
                source_not_ready_mv += mv_d

    def _w(part: Decimal) -> float:
        if nav_d <= 0:
            return 0.0
        return float(part / nav_d)

    top_issuers = sorted(
        (
            {
                "issuer_key": b["issuer_key"],
                "issuer_title": b["issuer_title"],
                "market_value": float(b["market_value"]),
                "weight": _w(Decimal(str(b["market_value"]))),
                "availability_status": b["availability_status"],
                "rating_raw": b["rating_raw"],
                "agency_code": b["agency_code"],
                "symbols": b["symbols"],
            }
            for b in issuers.values()
        ),
        key=lambda x: -x["weight"],
    )[:10]

    return {
        "government_weight": _w(gov_mv),
        "corporate_weight": _w(corp_mv),
        "rated_corporate_weight": _w(rated_corp_mv),
        "unrated_corporate_weight": _w(unrated_corp_mv),
        "credit_data_unavailable_weight": _w(source_not_ready_mv),
        "no_rating_found_weight": _w(no_rating_mv),
        "mapping_failed_weight": _w(mapping_failed_mv),
        "other_bond_weight": _w(other_bond_mv),
        "bond_weight": _w(bond_mv_total),
        "government_market_value": float(gov_mv),
        "corporate_market_value": float(corp_mv),
        "bond_market_value": float(bond_mv_total),
        "top_issuers": top_issuers,
        "provider_verdict": "NOT_READY",
        "notes": [
            "Value-weighted coverage — not instrument counts.",
            "SOURCE_NOT_READY ≠ NO_RATING_FOUND.",
            "OFZ → government_weight (not fabricated AAA).",
            "No auto sell/buy from ratings.",
            "rated_corporate_weight is 0 until accepted provider stores ratings.",
        ],
        "advisory": True,
    }
