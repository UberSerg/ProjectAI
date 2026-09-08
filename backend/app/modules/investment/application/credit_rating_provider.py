"""CreditRatingProvider port — readiness without inventing ratings.

Live probe 2026-09-08:
- MOEX CCI /iss/cci/rating/* → HTTP 200 empty, X-MicexPassport-Marker=denied
- ACRA structured feed is paid commercial CSV
- Expert RA — no free bulk API confirmed
- Unofficial scrapes FORBIDDEN

Production status: NOT_READY / READY_REQUIRES_ACCESS until credentials exist.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.investment.domain.credit_intelligence import (
    CreditAvailabilityStatus,
    CreditProviderReadiness,
    CreditRatingRecord,
    CreditSubjectType,
    assess_credit_availability,
    is_russian_federal_government_bond,
)


@dataclass(frozen=True, slots=True)
class CreditProviderFetchResult:
    records: tuple[CreditRatingRecord, ...]
    searched: bool
    availability: CreditAvailabilityStatus
    note: str | None = None


class CreditRatingProvider(Protocol):
    """Port for a lawful, audited credit-rating source."""

    name: str

    def fetch_ratings(
        self,
        *,
        subject_type: CreditSubjectType,
        subject_key: str,
    ) -> CreditProviderFetchResult:
        ...

    def readiness(self) -> dict[str, Any]:
        ...


class NotReadyCreditRatingProvider:
    """Default provider — documents why ingest is blocked. Never fabricates ratings."""

    name = "NOT_READY"

    def __init__(self, *, reasons: Sequence[str] | None = None) -> None:
        self._reasons = list(
            reasons
            or (
                "MOEX_CCI_PASSPORT_DENIED",
                "ACRA_PAID_FEED_ONLY",
                "EXPERT_RA_NO_FREE_API",
                "NO_SCRAPE_CANONICAL",
            )
        )

    def fetch_ratings(
        self,
        *,
        subject_type: CreditSubjectType,
        subject_key: str,
    ) -> CreditProviderFetchResult:
        return CreditProviderFetchResult(
            records=(),
            searched=False,
            availability=CreditAvailabilityStatus.SOURCE_NOT_READY,
            note="provider_not_ready",
        )

    def readiness(self) -> dict[str, Any]:
        return {
            "status": CreditProviderReadiness.NOT_READY.value,
            "operational_suitability": CreditProviderReadiness.READY_REQUIRES_ACCESS.value,
            "provider": self.name,
            "accepted": False,
            "reasons": list(self._reasons),
            "notes": [
                "MOEX CCI returns empty body with X-MicexPassport-Marker=denied without subscription.",
                "ACRA offers paid automated CSV; HTML scrape is not canonical.",
                "Expert RA has no confirmed free machine-readable bulk API.",
                "Do not invent ratings from yield, name, or OFZ → fake AAA.",
            ],
            "as_of": date.today().isoformat(),
        }


def get_credit_rating_provider() -> CreditRatingProvider:
    """Resolve provider from env/repo. Currently always NOT_READY."""
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.credit_sync_enabled:
        return NotReadyCreditRatingProvider(
            reasons=(
                "CREDIT_SYNC_ENABLED=false",
                "MOEX_CCI_PASSPORT_DENIED",
                "ACRA_PAID_FEED_ONLY",
                "EXPERT_RA_NO_FREE_API",
                "NO_SCRAPE_CANONICAL",
            )
        )
    return NotReadyCreditRatingProvider(
        reasons=(
            "CREDIT_SYNC_ENABLED=true_but_no_accepted_provider_implementation",
            "MOEX_CCI_PASSPORT_DENIED",
            "ACRA_PAID_FEED_ONLY",
            "EXPERT_RA_NO_FREE_API",
        )
    )


def credit_coverage_v1(session: Session) -> dict[str, Any]:
    """Honest credit coverage / readiness for APIs and System Data Coverage."""
    from app.infrastructure.market.models import Instrument
    from app.modules.investment.infrastructure.models import (
        BondTerm,
        CreditRatingObservation,
        CreditSyncJob,
    )

    provider = get_credit_rating_provider()
    provider_ready = provider.readiness()

    bonds_total = int(
        session.scalar(
            select(func.count()).select_from(Instrument).where(Instrument.asset_class == "bond")
        )
        or 0
    )
    ofz_count = 0
    corporate_count = 0
    try:
        rows = session.execute(
            select(BondTerm.bond_type, func.count()).group_by(BondTerm.bond_type)
        ).all()
        for bt, cnt in rows:
            if is_russian_federal_government_bond(str(bt)):
                ofz_count += int(cnt)
            elif str(bt) == "Corporate":
                corporate_count += int(cnt)
    except Exception:  # noqa: BLE001
        pass

    obs_total = 0
    current_ratings = 0
    try:
        obs_total = int(session.scalar(select(func.count()).select_from(CreditRatingObservation)) or 0)
        current_ratings = int(
            session.scalar(
                select(func.count())
                .select_from(CreditRatingObservation)
                .where(
                    CreditRatingObservation.availability_status
                    == CreditAvailabilityStatus.CURRENT_RATING_AVAILABLE.value
                )
            )
            or 0
        )
    except Exception:  # noqa: BLE001
        obs_total = 0
        current_ratings = 0

    job_counts: dict[str, int] = {}
    try:
        jrows = session.execute(
            select(CreditSyncJob.status, func.count()).group_by(CreditSyncJob.status)
        ).all()
        job_counts = {str(s): int(c) for s, c in jrows}
    except Exception:  # noqa: BLE001
        job_counts = {}

    return {
        "as_of": date.today().isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": provider_ready,
        "verdict": "NOT_READY" if not provider_ready.get("accepted") else "READY",
        "ingest_enabled": False,
        "bonds_in_master": bonds_total,
        "ofz_government_terms": ofz_count,
        "corporate_terms": corporate_count,
        "rating_observations_stored": obs_total,
        "current_ratings_available": current_ratings,
        "rated_corporate_weight_ready": False,
        "sync_jobs": job_counts,
        "availability_statuses": [s.value for s in CreditAvailabilityStatus],
        "notes": [
            "SOURCE_NOT_READY ≠ NO_RATING_FOUND",
            "OFZ → GOVERNMENT_RUSSIAN_FEDERAL (not fabricated AAA)",
            "No scrape / no yield-inferred ratings",
        ],
    }


def resolve_instrument_credit(
    session: Session,
    *,
    instrument_id: int,
    symbol: str,
    bond_type: str | None,
    subtype: str | None = None,
) -> dict[str, Any]:
    """Resolve credit assessment for one instrument using stored obs + provider readiness."""
    from app.modules.investment.infrastructure.models import CreditRatingObservation

    provider = get_credit_rating_provider()
    ready = bool(provider.readiness().get("accepted"))

    observed: CreditRatingRecord | None = None
    mapping_failed = False
    searched_no_rating = False
    try:
        row = session.scalar(
            select(CreditRatingObservation)
            .where(CreditRatingObservation.instrument_id == instrument_id)
            .order_by(CreditRatingObservation.observed_at.desc())
            .limit(1)
        )
        if row is not None:
            if row.availability_status == CreditAvailabilityStatus.MAPPING_FAILED.value:
                mapping_failed = True
            elif row.availability_status == CreditAvailabilityStatus.NO_RATING_FOUND.value:
                searched_no_rating = True
            elif row.rating_raw and row.agency_code:
                observed = CreditRatingRecord(
                    subject_type=CreditSubjectType(row.subject_type),
                    subject_key=row.subject_key,
                    agency_code=row.agency_code,
                    rating_raw=row.rating_raw,
                    scale=row.scale,
                    outlook=row.outlook,
                    action_type=row.action_type,
                    action_date=row.action_date,
                    known_at=row.known_at,
                    known_at_quality=row.known_at_quality or "UNKNOWN",
                    source=row.source,
                    source_record_id=row.source_record_id,
                )
    except Exception:  # noqa: BLE001
        pass

    assessment = assess_credit_availability(
        instrument_id=instrument_id,
        subject_key=symbol,
        bond_type=bond_type,
        provider_ready=ready,
        observed_rating=observed,
        mapping_failed=mapping_failed,
        searched_no_rating=searched_no_rating,
        subtype=subtype,
    )
    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "availability_status": assessment.availability.value,
        "credit_status": assessment.credit_status,
        "rating_raw": assessment.rating_raw,
        "agency_code": assessment.agency_code,
        "scale": assessment.scale,
        "outlook": assessment.outlook,
        "action_date": assessment.action_date.isoformat() if assessment.action_date else None,
        "known_at": (
            assessment.known_at.isoformat()
            if isinstance(assessment.known_at, date | datetime)
            else None
        ),
        "source": assessment.source,
        "risk_flags": list(assessment.risk_flags),
        "limitations": list(assessment.limitations),
        "bond_type": assessment.bond_type,
        "credit_available": assessment.availability
        is CreditAvailabilityStatus.CURRENT_RATING_AVAILABLE,
        "is_government_debt": assessment.availability
        is CreditAvailabilityStatus.GOVERNMENT_RUSSIAN_FEDERAL,
    }


def sync_credit_ratings_noop(session: Session) -> dict[str, Any]:
    """Celery entry — gated; no-ops while provider NOT_READY."""
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.credit_sync_enabled:
        return {
            "status": "DISABLED",
            "reason": "CREDIT_SYNC_ENABLED=false",
            "ingested": 0,
        }
    provider = get_credit_rating_provider()
    readiness = provider.readiness()
    if not readiness.get("accepted"):
        return {
            "status": "NOT_READY",
            "provider": readiness,
            "ingested": 0,
            "note": "No accepted credit provider; nothing ingested.",
        }
    # Future: claim credit_sync_jobs and persist observations.
    return {
        "status": "READY",
        "provider": readiness,
        "ingested": 0,
        "note": "Accepted provider path not implemented in V1.",
    }
