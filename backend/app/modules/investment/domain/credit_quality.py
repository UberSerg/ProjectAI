"""Credit quality foundation — framework-free.

Accounting quality ≠ investment quality.
No fake credit scores. No invented SAFE/LOW_RISK labels.
Ratings are issuer-level facts with explicit agency/scale/date — never mixed without mapping.

V1 adds CreditAvailabilityStatus via credit_intelligence:
SOURCE_NOT_READY ≠ NO_RATING_FOUND; OFZ → GOVERNMENT_RUSSIAN_FEDERAL (not fake AAA).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from app.modules.investment.domain.credit_intelligence import (
    CreditAvailabilityStatus,
    assess_credit_availability,
    is_russian_federal_government_bond,
)


class CreditStatus(StrEnum):
    """Legacy + V1 availability statuses (string-compatible with assessments)."""

    UNKNOWN = "UNKNOWN"
    AVAILABLE = "AVAILABLE"
    NOT_RATED = "NOT_RATED"
    CONFLICT = "CONFLICT"
    STALE = "STALE"
    # V1 — prefer these over overloaded UNKNOWN
    SOURCE_NOT_READY = "SOURCE_NOT_READY"
    NO_RATING_FOUND = "NO_RATING_FOUND"
    MAPPING_FAILED = "MAPPING_FAILED"
    CURRENT_RATING_AVAILABLE = "CURRENT_RATING_AVAILABLE"
    GOVERNMENT_RUSSIAN_FEDERAL = "GOVERNMENT_RUSSIAN_FEDERAL"


class RiskFlag(StrEnum):
    CREDIT_UNKNOWN = "CREDIT_UNKNOWN"
    NO_RATING = "NO_RATING"
    SOURCE_NOT_READY = "SOURCE_NOT_READY"
    DATA_STALE = "DATA_STALE"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    UNKNOWN_LIQUIDITY = "UNKNOWN_LIQUIDITY"
    ACCOUNTING_UNSUPPORTED = "ACCOUNTING_UNSUPPORTED"
    CORPORATE_WITHOUT_RATING = "CORPORATE_WITHOUT_RATING"
    MAPPING_FAILED = "MAPPING_FAILED"
    GOVERNMENT_DEBT = "GOVERNMENT_DEBT"


@dataclass(frozen=True, slots=True)
class CreditQualityAssessment:
    instrument_id: int
    issuer_id: int | None
    credit_status: CreditStatus
    rating_source: str | None
    rating_value: str | None
    rating_date: date | None
    rating_known_at: date | datetime | None
    source: str
    limitations: tuple[str, ...]
    risk_flags: tuple[str, ...] = ()
    agency: str | None = None
    scale: str | None = None
    availability_status: CreditAvailabilityStatus | None = None


@dataclass(frozen=True, slots=True)
class IssuerCreditProfile:
    issuer_id: int | None
    rating_summary: str | None
    sector: str | None
    credit_quality_status: CreditStatus
    source: str
    updated_at: datetime | None
    limitations: tuple[str, ...] = ()


def _to_credit_status(availability: CreditAvailabilityStatus) -> CreditStatus:
    mapping = {
        CreditAvailabilityStatus.SOURCE_NOT_READY: CreditStatus.SOURCE_NOT_READY,
        CreditAvailabilityStatus.NO_RATING_FOUND: CreditStatus.NO_RATING_FOUND,
        CreditAvailabilityStatus.MAPPING_FAILED: CreditStatus.MAPPING_FAILED,
        CreditAvailabilityStatus.CURRENT_RATING_AVAILABLE: CreditStatus.CURRENT_RATING_AVAILABLE,
        CreditAvailabilityStatus.GOVERNMENT_RUSSIAN_FEDERAL: CreditStatus.GOVERNMENT_RUSSIAN_FEDERAL,
    }
    return mapping[availability]


def assess_credit_from_observed(
    *,
    instrument_id: int,
    issuer_id: int | None,
    bond_type: str,
    stored_credit_status: str | None,
    raw_fields: dict | None,
    as_of: date,
    rating_value: str | None = None,
    rating_agency: str | None = None,
    rating_date: date | None = None,
    rating_known_at: date | datetime | None = None,
    rating_source: str | None = None,
    stale_after_days: int = 365,
    provider_ready: bool = False,
    subtype: str | None = None,
) -> CreditQualityAssessment:
    """Build credit assessment without inventing ratings.

    Government/OFZ → GOVERNMENT_RUSSIAN_FEDERAL (not fake AAA).
    Provider not ready → SOURCE_NOT_READY (≠ NO_RATING_FOUND).
    """
    limitations = [
        "No default prediction",
        "No invented SAFE / GUARANTEED / LOW_RISK labels",
        "Agency AAA values are not comparable across agencies without mapping",
        "Absence of rating is not safety",
        "OFZ is government debt — not a fabricated corporate AAA",
    ]
    flags: list[str] = []
    raw = raw_fields or {}

    # OFZ / Russian federal government first — never treat as unrated corporate.
    if is_russian_federal_government_bond(bond_type, subtype=subtype):
        intel = assess_credit_availability(
            instrument_id=instrument_id,
            subject_key=str(instrument_id),
            bond_type=bond_type,
            provider_ready=provider_ready,
            subtype=subtype,
        )
        return CreditQualityAssessment(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            credit_status=_to_credit_status(intel.availability),
            rating_source=None,
            rating_value=None,
            rating_date=None,
            rating_known_at=None,
            source=intel.source,
            limitations=intel.limitations,
            risk_flags=(RiskFlag.GOVERNMENT_DEBT.value,),
            agency=None,
            scale=None,
            availability_status=intel.availability,
        )

    # Observed MOEX raw rating fields only — never invent.
    observed_value = rating_value or _first_str(
        raw, ("RATING", "CREDITRATING", "RATINGVALUE", "RATING_VALUE")
    )
    observed_agency = rating_agency or _first_str(
        raw, ("RATINGAGENCY", "AGENCY", "RATING_AGENCY")
    )
    observed_date = rating_date or _parse_date(
        raw.get("RATINGDATE") or raw.get("RATING_DATE")
    )

    if observed_value and observed_agency:
        status = CreditStatus.CURRENT_RATING_AVAILABLE
        avail = CreditAvailabilityStatus.CURRENT_RATING_AVAILABLE
        # Keep AVAILABLE alias for older consumers
        if observed_date is not None and (as_of - observed_date).days > stale_after_days:
            status = CreditStatus.STALE
            flags.append(RiskFlag.DATA_STALE.value)
        return CreditQualityAssessment(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            credit_status=status,
            rating_source=rating_source or "OBSERVED_RAW_FIELD",
            rating_value=str(observed_value),
            rating_date=observed_date,
            rating_known_at=rating_known_at or observed_date,
            source=rating_source or "OBSERVED_RAW_FIELD",
            limitations=tuple(limitations),
            risk_flags=tuple(flags),
            agency=str(observed_agency),
            scale=None,
            availability_status=avail if status is CreditStatus.CURRENT_RATING_AVAILABLE else None,
        )

    # Explicit NOT_RATED / NO_RATING_FOUND only when source searched or marked.
    if (
        stored_credit_status in {"NOT_RATED", "NO_RATING_FOUND"}
        or str(raw.get("RATING_STATUS") or "").upper() in {"NOT_RATED", "NO_RATING_FOUND"}
    ):
        intel = assess_credit_availability(
            instrument_id=instrument_id,
            subject_key=str(instrument_id),
            bond_type=bond_type,
            provider_ready=True,
            searched_no_rating=True,
            subtype=subtype,
        )
        return CreditQualityAssessment(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            credit_status=CreditStatus.NO_RATING_FOUND,
            rating_source=None,
            rating_value=None,
            rating_date=None,
            rating_known_at=None,
            source="NO_RATING_OBSERVED",
            limitations=intel.limitations,
            risk_flags=tuple(intel.risk_flags),
            availability_status=CreditAvailabilityStatus.NO_RATING_FOUND,
        )

    # Default: source not ready (production) — do not call this NO_RATING_FOUND.
    if not provider_ready:
        intel = assess_credit_availability(
            instrument_id=instrument_id,
            subject_key=str(instrument_id),
            bond_type=bond_type,
            provider_ready=False,
            subtype=subtype,
        )
        return CreditQualityAssessment(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            credit_status=CreditStatus.SOURCE_NOT_READY,
            rating_source=None,
            rating_value=None,
            rating_date=None,
            rating_known_at=None,
            source=intel.source,
            limitations=intel.limitations,
            risk_flags=tuple(intel.risk_flags),
            availability_status=CreditAvailabilityStatus.SOURCE_NOT_READY,
        )

    flags.append(RiskFlag.CREDIT_UNKNOWN.value)
    flags.append(RiskFlag.NO_RATING.value)
    if bond_type == "Corporate":
        flags.append(RiskFlag.CORPORATE_WITHOUT_RATING.value)

    return CreditQualityAssessment(
        instrument_id=instrument_id,
        issuer_id=issuer_id,
        credit_status=CreditStatus.UNKNOWN,
        rating_source=None,
        rating_value=None,
        rating_date=None,
        rating_known_at=None,
        source="NO_PUBLIC_RATING_IN_PIPELINE",
        limitations=tuple(limitations)
        + (
            "Provider marked ready but no observation stored.",
        ),
        risk_flags=tuple(dict.fromkeys(flags)),
        availability_status=None,
    )


def _first_str(raw: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
