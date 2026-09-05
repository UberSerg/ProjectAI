"""Credit quality foundation V0 — framework-free.

Accounting quality ≠ investment quality.
No fake credit scores. No invented SAFE/LOW_RISK labels.
Ratings are issuer-level facts with explicit agency/scale/date — never mixed without mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class CreditStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    AVAILABLE = "AVAILABLE"
    NOT_RATED = "NOT_RATED"
    CONFLICT = "CONFLICT"
    STALE = "STALE"


class RiskFlag(StrEnum):
    CREDIT_UNKNOWN = "CREDIT_UNKNOWN"
    NO_RATING = "NO_RATING"
    DATA_STALE = "DATA_STALE"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    UNKNOWN_LIQUIDITY = "UNKNOWN_LIQUIDITY"
    ACCOUNTING_UNSUPPORTED = "ACCOUNTING_UNSUPPORTED"
    CORPORATE_WITHOUT_RATING = "CORPORATE_WITHOUT_RATING"


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


@dataclass(frozen=True, slots=True)
class IssuerCreditProfile:
    issuer_id: int | None
    rating_summary: str | None
    sector: str | None
    credit_quality_status: CreditStatus
    source: str
    updated_at: datetime | None
    limitations: tuple[str, ...] = ()


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
) -> CreditQualityAssessment:
    """Build credit assessment without inventing ratings.

    If no agency rating is available → UNKNOWN or NOT_RATED (never SAFE).
    """
    limitations = [
        "No default prediction",
        "No invented SAFE / GUARANTEED / LOW_RISK labels",
        "Agency AAA values are not comparable across agencies without mapping",
        "Absence of rating is not safety",
    ]
    flags: list[str] = []
    raw = raw_fields or {}

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
        status = CreditStatus.AVAILABLE
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
        )

    # Explicit NOT_RATED only when source says so — otherwise UNKNOWN.
    if stored_credit_status == "NOT_RATED" or str(raw.get("RATING_STATUS") or "").upper() == "NOT_RATED":
        flags.extend([RiskFlag.NO_RATING.value, RiskFlag.CREDIT_UNKNOWN.value])
        if bond_type == "Corporate":
            flags.append(RiskFlag.CORPORATE_WITHOUT_RATING.value)
        return CreditQualityAssessment(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            credit_status=CreditStatus.NOT_RATED,
            rating_source=None,
            rating_value=None,
            rating_date=None,
            rating_known_at=None,
            source="NO_RATING_OBSERVED",
            limitations=tuple(limitations)
            + ("Instrument marked not rated — not equivalent to investment grade.",),
            risk_flags=tuple(dict.fromkeys(flags)),
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
            "MOEX ISS bond securities sample does not provide licensed agency ratings in V0.",
            "Paid rating feeds require READY_REQUIRES_ACCESS — not bypassed.",
        ),
        risk_flags=tuple(dict.fromkeys(flags)),
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
