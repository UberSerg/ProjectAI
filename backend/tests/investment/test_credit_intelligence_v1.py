"""Credit Intelligence V1 — provider NOT_READY, OFZ government, status distinctions."""

from __future__ import annotations

from datetime import date

from app.modules.investment.application.credit_rating_provider import (
    NotReadyCreditRatingProvider,
    get_credit_rating_provider,
)
from app.modules.investment.domain.credit_intelligence import (
    CreditAvailabilityStatus,
    CreditSubjectType,
    assess_credit_availability,
)
from app.modules.investment.domain.credit_quality import (
    CreditStatus,
    assess_credit_from_observed,
)


def test_provider_not_ready_by_default() -> None:
    provider = get_credit_rating_provider()
    readiness = provider.readiness()
    assert readiness["accepted"] is False
    assert readiness["status"] == "NOT_READY"
    assert "MOEX_CCI_PASSPORT_DENIED" in readiness["reasons"] or any(
        "CCI" in r or "NOT_READY" in r or "CREDIT_SYNC" in r for r in readiness["reasons"]
    )
    result = provider.fetch_ratings(
        subject_type=CreditSubjectType.ISSUE,
        subject_key="RU000A0JX0J2",
    )
    assert result.records == ()
    assert result.availability is CreditAvailabilityStatus.SOURCE_NOT_READY
    assert result.searched is False


def test_source_not_ready_ne_no_rating_found() -> None:
    not_ready = assess_credit_availability(
        instrument_id=1,
        subject_key="CORP1",
        bond_type="Corporate",
        provider_ready=False,
    )
    no_rating = assess_credit_availability(
        instrument_id=2,
        subject_key="CORP2",
        bond_type="Corporate",
        provider_ready=True,
        searched_no_rating=True,
    )
    assert not_ready.availability is CreditAvailabilityStatus.SOURCE_NOT_READY
    assert no_rating.availability is CreditAvailabilityStatus.NO_RATING_FOUND
    assert not_ready.availability != no_rating.availability


def test_government_ofz_not_fake_rated() -> None:
    ofz = assess_credit_from_observed(
        instrument_id=10,
        issuer_id=None,
        bond_type="Government",
        stored_credit_status="UNKNOWN",
        raw_fields={},
        as_of=date(2026, 9, 8),
        provider_ready=False,
        subtype="ofz_gov",
    )
    assert ofz.credit_status is CreditStatus.GOVERNMENT_RUSSIAN_FEDERAL
    assert ofz.availability_status is CreditAvailabilityStatus.GOVERNMENT_RUSSIAN_FEDERAL
    assert ofz.rating_value is None
    assert "GOVERNMENT_DEBT" in ofz.risk_flags


def test_corporate_defaults_to_source_not_ready() -> None:
    corp = assess_credit_from_observed(
        instrument_id=11,
        issuer_id=None,
        bond_type="Corporate",
        stored_credit_status="UNKNOWN",
        raw_fields={},
        as_of=date(2026, 9, 8),
        provider_ready=False,
    )
    assert corp.credit_status is CreditStatus.SOURCE_NOT_READY
    assert corp.availability_status is CreditAvailabilityStatus.SOURCE_NOT_READY
    assert "SOURCE_NOT_READY" in corp.risk_flags


def test_not_ready_provider_class() -> None:
    p = NotReadyCreditRatingProvider()
    assert p.name == "NOT_READY"
    assert p.fetch_ratings(
        subject_type=CreditSubjectType.ISSUER, subject_key="X"
    ).searched is False
