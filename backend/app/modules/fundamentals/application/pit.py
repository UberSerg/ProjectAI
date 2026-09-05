"""Point-in-time reads over the fundamentals schema.

This layer only loads rows and converts them into domain records; every visibility and
versioning decision belongs to ``domain.pit_rules``. Queries additionally filter
``known_at <= as_of`` in SQL so a large history never has to be materialised.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fundamentals.domain import pit_rules
from app.modules.fundamentals.domain.types import (
    CorporateEventRef,
    CorporateEventType,
    DividendEventRef,
    DividendState,
    DividendStatus,
    FactRef,
    FundamentalsState,
    MappingStatus,
    NormalizationStatus,
    PeriodType,
    QualityStatus,
    ReportingStandard,
    ReportRef,
    ReportStatus,
)
from app.modules.fundamentals.infrastructure.models import (
    CorporateEvent,
    DividendEvent,
    FinancialFact,
    FinancialReport,
    SecurityIssuerMapping,
)

# How an instrument was attached to an issuer at `as_of`.
BASIS_DATED_WINDOW = "DATED_WINDOW"
BASIS_CURRENT_ONLY = "CURRENT_ONLY"
BASIS_UNMAPPED = "UNMAPPED"


@dataclass(frozen=True, slots=True)
class IssuerResolution:
    """``basis`` is CURRENT_ONLY when only an open-ended mapping exists: issuer identity
    is then assumed stable over time, which is an identity assumption, not market data."""

    issuer_id: int | None
    basis: str
    mapping_status: str = MappingStatus.UNMAPPED.value


def resolve_issuer_for_instrument(
    session: Session, instrument_id: int, as_of: date
) -> IssuerResolution:
    rows = list(
        session.scalars(
            select(SecurityIssuerMapping).where(
                SecurityIssuerMapping.instrument_id == instrument_id,
                SecurityIssuerMapping.mapping_status == MappingStatus.MAPPED.value,
                SecurityIssuerMapping.issuer_id.is_not(None),
            )
        )
    )
    dated = [
        row
        for row in rows
        if row.valid_from is not None
        and row.valid_from <= as_of
        and (row.valid_to is None or as_of < row.valid_to)
    ]
    if dated:
        return IssuerResolution(dated[0].issuer_id, BASIS_DATED_WINDOW, MappingStatus.MAPPED.value)
    current = [row for row in rows if row.valid_from is None and row.valid_to is None]
    if current:
        return IssuerResolution(
            current[0].issuer_id, BASIS_CURRENT_ONLY, MappingStatus.MAPPED.value
        )
    return IssuerResolution(None, BASIS_UNMAPPED)


def report_ref(row: FinancialReport) -> ReportRef:
    return ReportRef(
        report_id=row.id,
        issuer_id=row.issuer_id,
        reporting_standard=ReportingStandard(row.reporting_standard),
        period_type=PeriodType(row.period_type),
        period_start=row.period_start,
        period_end=row.period_end,
        known_at=row.known_at,
        report_version=row.report_version,
        is_restatement=row.is_restatement,
        source=row.source,
        status=ReportStatus(row.status),
        currency=row.currency,
        unit_scale=row.unit_scale,
        published_at_known=row.published_at is not None,
    )


def fact_ref(row: FinancialFact) -> FactRef:
    return FactRef(
        metric_code=row.metric_code,
        value=row.value,
        normalization_status=NormalizationStatus(row.normalization_status),
        quality_status=QualityStatus(row.quality_status),
        currency=row.currency,
        unit_scale=row.unit_scale,
        source_metric_name=row.source_metric_name,
        report_id=row.report_id,
    )


def dividend_ref(row: DividendEvent) -> DividendEventRef:
    return DividendEventRef(
        event_id=row.id,
        issuer_id=row.issuer_id,
        instrument_id=row.instrument_id,
        known_at=row.known_at,
        status=DividendStatus(row.status),
        source=row.source,
        announcement_date=row.announcement_date,
        board_recommendation_date=row.board_recommendation_date,
        shareholder_approval_date=row.shareholder_approval_date,
        record_date=row.record_date,
        ex_date=row.ex_date,
        payment_date=row.payment_date,
        amount_per_share=row.amount_per_share,
        currency=row.currency,
        version=row.version,
        supersedes_id=row.supersedes_id,
    )


def corporate_event_ref(row: CorporateEvent) -> CorporateEventRef | None:
    try:
        event_type = CorporateEventType(row.event_type)
    except ValueError:
        return None
    return CorporateEventRef(
        event_id=row.id,
        issuer_id=row.issuer_id,
        instrument_id=row.instrument_id,
        event_type=event_type,
        event_date=row.event_date,
        known_at=row.known_at,
        effective_date=row.effective_date,
        source=row.source,
        external_id=row.external_id,
    )


def load_visible_reports(
    session: Session,
    issuer_id: int,
    as_of: date,
    *,
    reporting_standard: ReportingStandard | None = None,
) -> tuple[ReportRef, ...]:
    stmt = select(FinancialReport).where(
        FinancialReport.issuer_id == issuer_id,
        FinancialReport.known_at <= as_of,
        FinancialReport.status != ReportStatus.REJECTED.value,
    )
    if reporting_standard is not None:
        stmt = stmt.where(FinancialReport.reporting_standard == reporting_standard.value)
    rows = session.scalars(stmt).all()
    return pit_rules.visible_reports([report_ref(row) for row in rows], as_of)


def load_facts(session: Session, report_id: int) -> tuple[FactRef, ...]:
    rows = session.scalars(
        select(FinancialFact).where(FinancialFact.report_id == report_id)
    ).all()
    return tuple(fact_ref(row) for row in rows)


def get_fundamentals_as_of(
    session: Session,
    issuer_id: int,
    as_of: date,
    *,
    reporting_standard: ReportingStandard | None = None,
) -> FundamentalsState:
    """Latest disclosed report for an issuer plus its facts. Empty when nothing is known."""
    reports = load_visible_reports(
        session, issuer_id, as_of, reporting_standard=reporting_standard
    )
    latest = pit_rules.latest_report(reports, as_of)
    facts = load_facts(session, latest.report_id) if latest and latest.report_id else ()
    return FundamentalsState(
        as_of=as_of,
        issuer_id=issuer_id,
        latest_report=latest,
        facts=facts,
        visible_reports=len(reports),
    )


def load_visible_dividend_events(
    session: Session,
    as_of: date,
    *,
    instrument_id: int | None = None,
    issuer_id: int | None = None,
) -> tuple[DividendEventRef, ...]:
    stmt = select(DividendEvent).where(DividendEvent.known_at <= as_of)
    if instrument_id is not None:
        stmt = stmt.where(DividendEvent.instrument_id == instrument_id)
    if issuer_id is not None:
        stmt = stmt.where(DividendEvent.issuer_id == issuer_id)
    rows = session.scalars(stmt).all()
    return pit_rules.visible_dividend_events([dividend_ref(row) for row in rows], as_of)


def get_dividend_state_as_of(
    session: Session,
    as_of: date,
    *,
    instrument_id: int | None = None,
    issuer_id: int | None = None,
) -> DividendState:
    """Most recent dividend disclosure known at ``as_of``; ``is_known`` False when none."""
    events = load_visible_dividend_events(
        session, as_of, instrument_id=instrument_id, issuer_id=issuer_id
    )
    return pit_rules.latest_dividend_state(events, as_of)


def get_upcoming_dividend_as_of(
    session: Session,
    as_of: date,
    *,
    instrument_id: int | None = None,
    issuer_id: int | None = None,
) -> DividendState | None:
    events = load_visible_dividend_events(
        session, as_of, instrument_id=instrument_id, issuer_id=issuer_id
    )
    return pit_rules.next_upcoming_dividend(events, as_of)


def load_visible_corporate_events(
    session: Session,
    as_of: date,
    *,
    instrument_id: int | None = None,
    issuer_id: int | None = None,
) -> tuple[CorporateEventRef, ...]:
    stmt = select(CorporateEvent).where(CorporateEvent.known_at <= as_of)
    if instrument_id is not None:
        stmt = stmt.where(CorporateEvent.instrument_id == instrument_id)
    if issuer_id is not None:
        stmt = stmt.where(CorporateEvent.issuer_id == issuer_id)
    rows = session.scalars(stmt).all()
    refs = [ref for row in rows if (ref := corporate_event_ref(row)) is not None]
    return pit_rules.visible_corporate_events(refs, as_of)
