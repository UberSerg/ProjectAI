"""Credit Intelligence V1 — availability statuses without inventing ratings.

CreditRatingProvider may be NOT_READY. That is distinct from searching an
accepted source and finding no rating for a subject.
OFZ / Russian federal government debt is GOVERNMENT_RUSSIAN_FEDERAL — not a
fabricated AAA corporate rating.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class CreditSubjectType(StrEnum):
    ISSUER = "ISSUER"
    ISSUE = "ISSUE"


class CreditObservationStatus(StrEnum):
    CURRENT = "CURRENT"
    WITHDRAWN = "WITHDRAWN"
    UNKNOWN = "UNKNOWN"


class CreditAvailabilityStatus(StrEnum):
    """Honest coverage / readiness — do not overload UNKNOWN."""

    SOURCE_NOT_READY = "SOURCE_NOT_READY"
    NO_RATING_FOUND = "NO_RATING_FOUND"
    MAPPING_FAILED = "MAPPING_FAILED"
    CURRENT_RATING_AVAILABLE = "CURRENT_RATING_AVAILABLE"
    GOVERNMENT_RUSSIAN_FEDERAL = "GOVERNMENT_RUSSIAN_FEDERAL"


class CreditProviderReadiness(StrEnum):
    NOT_READY = "NOT_READY"
    READY_REQUIRES_ACCESS = "READY_REQUIRES_ACCESS"
    READY = "READY"


@dataclass(frozen=True, slots=True)
class CreditRatingRecord:
    """Normalized agency rating observation from an accepted provider (future)."""

    subject_type: CreditSubjectType
    subject_key: str
    agency_code: str
    rating_raw: str | None
    scale: str | None = None
    outlook: str | None = None
    action_type: str | None = None
    action_date: date | None = None
    known_at: date | None = None
    known_at_quality: str = "UNKNOWN"
    source: str | None = None
    source_record_id: str | None = None
    status: CreditObservationStatus = CreditObservationStatus.UNKNOWN


@dataclass(frozen=True, slots=True)
class CreditSubjectAssessment:
    instrument_id: int | None
    subject_type: CreditSubjectType
    subject_key: str
    availability: CreditAvailabilityStatus
    credit_status: str
    rating_raw: str | None
    agency_code: str | None
    scale: str | None
    outlook: str | None
    action_date: date | None
    known_at: date | datetime | None
    source: str
    risk_flags: tuple[str, ...]
    limitations: tuple[str, ...]
    bond_type: str | None = None


GOVERNMENT_BOND_TYPES = frozenset({"Government", "OFZ", "government"})


def is_russian_federal_government_bond(bond_type: str | None, *, subtype: str | None = None) -> bool:
    bt = (bond_type or "").strip()
    st = (subtype or "").strip().lower()
    if bt in GOVERNMENT_BOND_TYPES:
        return True
    return st in {"ofz_gov", "ofz", "government"}


def assess_credit_availability(
    *,
    instrument_id: int | None,
    subject_key: str,
    bond_type: str | None,
    provider_ready: bool,
    observed_rating: CreditRatingRecord | None = None,
    mapping_failed: bool = False,
    searched_no_rating: bool = False,
    subtype: str | None = None,
    subject_type: CreditSubjectType = CreditSubjectType.ISSUE,
) -> CreditSubjectAssessment:
    """Classify credit availability without inventing ratings."""
    limitations = [
        "No default prediction",
        "No invented SAFE / GUARANTEED / LOW_RISK / AAA labels",
        "Agency scales are not comparable without explicit mapping",
        "Absence of rating is not safety",
        "OFZ is government debt category — not a fabricated corporate AAA",
    ]

    if is_russian_federal_government_bond(bond_type, subtype=subtype):
        return CreditSubjectAssessment(
            instrument_id=instrument_id,
            subject_type=subject_type,
            subject_key=subject_key,
            availability=CreditAvailabilityStatus.GOVERNMENT_RUSSIAN_FEDERAL,
            credit_status=CreditAvailabilityStatus.GOVERNMENT_RUSSIAN_FEDERAL.value,
            rating_raw=None,
            agency_code=None,
            scale=None,
            outlook=None,
            action_date=None,
            known_at=None,
            source="BOND_TYPE_GOVERNMENT",
            risk_flags=(),
            limitations=tuple(limitations)
            + ("Russian Federation government debt (OFZ/TQOB) — sovereign category, not CRA rating.",),
            bond_type=bond_type,
        )

    if mapping_failed:
        return CreditSubjectAssessment(
            instrument_id=instrument_id,
            subject_type=subject_type,
            subject_key=subject_key,
            availability=CreditAvailabilityStatus.MAPPING_FAILED,
            credit_status=CreditAvailabilityStatus.MAPPING_FAILED.value,
            rating_raw=observed_rating.rating_raw if observed_rating else None,
            agency_code=observed_rating.agency_code if observed_rating else None,
            scale=observed_rating.scale if observed_rating else None,
            outlook=observed_rating.outlook if observed_rating else None,
            action_date=observed_rating.action_date if observed_rating else None,
            known_at=observed_rating.known_at if observed_rating else None,
            source="MAPPING_FAILED",
            risk_flags=("MAPPING_FAILED", "CREDIT_UNKNOWN"),
            limitations=tuple(limitations),
            bond_type=bond_type,
        )

    if observed_rating and observed_rating.rating_raw and observed_rating.agency_code:
        return CreditSubjectAssessment(
            instrument_id=instrument_id,
            subject_type=subject_type,
            subject_key=subject_key,
            availability=CreditAvailabilityStatus.CURRENT_RATING_AVAILABLE,
            credit_status=CreditAvailabilityStatus.CURRENT_RATING_AVAILABLE.value,
            rating_raw=observed_rating.rating_raw,
            agency_code=observed_rating.agency_code,
            scale=observed_rating.scale,
            outlook=observed_rating.outlook,
            action_date=observed_rating.action_date,
            known_at=observed_rating.known_at,
            source=observed_rating.source or "STORED_OBSERVATION",
            risk_flags=(),
            limitations=tuple(limitations),
            bond_type=bond_type,
        )

    if searched_no_rating and provider_ready:
        flags = ["NO_RATING", "CREDIT_UNKNOWN"]
        if (bond_type or "") == "Corporate":
            flags.append("CORPORATE_WITHOUT_RATING")
        return CreditSubjectAssessment(
            instrument_id=instrument_id,
            subject_type=subject_type,
            subject_key=subject_key,
            availability=CreditAvailabilityStatus.NO_RATING_FOUND,
            credit_status=CreditAvailabilityStatus.NO_RATING_FOUND.value,
            rating_raw=None,
            agency_code=None,
            scale=None,
            outlook=None,
            action_date=None,
            known_at=None,
            source="PROVIDER_SEARCHED_EMPTY",
            risk_flags=tuple(flags),
            limitations=tuple(limitations)
            + ("Accepted provider searched; no rating found for subject.",),
            bond_type=bond_type,
        )

    # Default production path: no accepted live provider → SOURCE_NOT_READY
    # (never conflate with NO_RATING_FOUND).
    flags = ["SOURCE_NOT_READY", "CREDIT_UNKNOWN"]
    if (bond_type or "") == "Corporate":
        flags.append("CORPORATE_WITHOUT_RATING")
    return CreditSubjectAssessment(
        instrument_id=instrument_id,
        subject_type=subject_type,
        subject_key=subject_key,
        availability=CreditAvailabilityStatus.SOURCE_NOT_READY,
        credit_status=CreditAvailabilityStatus.SOURCE_NOT_READY.value,
        rating_raw=None,
        agency_code=None,
        scale=None,
        outlook=None,
        action_date=None,
        known_at=None,
        source="CREDIT_PROVIDER_NOT_READY",
        risk_flags=tuple(dict.fromkeys(flags)),
        limitations=tuple(limitations)
        + (
            "MOEX CCI requires MicexPassport (denied on live probe).",
            "ACRA / Expert RA structured feeds require commercial access.",
            "Unofficial scrapes are forbidden as canonical credit source.",
        ),
        bond_type=bond_type,
    )
