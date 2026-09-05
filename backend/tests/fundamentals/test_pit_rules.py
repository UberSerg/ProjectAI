"""Point-in-time invariants: visibility, restatement versioning, dividend timing."""

from __future__ import annotations

from datetime import date

from app.modules.fundamentals.domain import pit_rules
from app.modules.fundamentals.domain.types import (
    DividendEventRef,
    DividendStatus,
    PeriodType,
    ReportingStandard,
    ReportRef,
)


def _report(
    *,
    period_end: date,
    known_at: date,
    version: int = 1,
    is_restatement: bool = False,
    report_id: int | None = None,
) -> ReportRef:
    return ReportRef(
        report_id=report_id,
        issuer_id=1,
        reporting_standard=ReportingStandard.IFRS,
        period_type=PeriodType.FY,
        period_end=period_end,
        known_at=known_at,
        report_version=version,
        is_restatement=is_restatement,
    )


def _dividend(
    *,
    known_at: date,
    record_date: date | None,
    version: int = 1,
    status: DividendStatus = DividendStatus.RECOMMENDED,
    amount: float | None = 10.0,
    announcement_date: date | None = None,
    event_id: int | None = None,
) -> DividendEventRef:
    return DividendEventRef(
        event_id=event_id,
        instrument_id=7,
        known_at=known_at,
        status=status,
        source="TEST",
        announcement_date=announcement_date,
        record_date=record_date,
        amount_per_share=amount,
        version=version,
    )


def test_report_invisible_before_known_at_and_visible_after() -> None:
    report = _report(period_end=date(2025, 12, 31), known_at=date(2026, 3, 20))

    assert pit_rules.latest_report([report], date(2026, 3, 19)) is None
    assert pit_rules.latest_report([report], date(2026, 3, 20)) is report
    assert pit_rules.latest_report([report], date(2026, 6, 1)) is report


def test_report_without_known_at_is_never_visible() -> None:
    unknown = ReportRef(
        issuer_id=1,
        reporting_standard=ReportingStandard.RAS,
        period_type=PeriodType.FY,
        period_end=date(2025, 12, 31),
        known_at=None,  # type: ignore[arg-type]
    )
    assert pit_rules.visible_reports([unknown], date(2030, 1, 1)) == ()


def test_restatement_replaces_original_only_after_it_is_disclosed() -> None:
    original = _report(
        period_end=date(2025, 12, 31), known_at=date(2026, 3, 20), version=1, report_id=1
    )
    restated = _report(
        period_end=date(2025, 12, 31),
        known_at=date(2026, 8, 10),
        version=2,
        is_restatement=True,
        report_id=2,
    )
    reports = [original, restated]

    assert pit_rules.latest_report(reports, date(2026, 5, 1)) is original
    assert pit_rules.latest_report(reports, date(2026, 8, 10)) is restated
    assert (
        pit_rules.effective_report_for_period(reports, date(2026, 8, 31), original.period_key)
        is restated
    )


def test_latest_report_prefers_newest_disclosed_period() -> None:
    fy2024 = _report(period_end=date(2024, 12, 31), known_at=date(2025, 3, 20))
    fy2025 = _report(period_end=date(2025, 12, 31), known_at=date(2026, 3, 20))

    assert pit_rules.latest_report([fy2024, fy2025], date(2026, 1, 15)) is fy2024
    assert pit_rules.latest_report([fy2024, fy2025], date(2026, 4, 1)) is fy2025


def test_dividend_recommendation_then_approval_timing() -> None:
    recommended = _dividend(
        known_at=date(2026, 4, 20),
        record_date=date(2026, 7, 10),
        version=1,
        status=DividendStatus.RECOMMENDED,
        amount=30.0,
        announcement_date=date(2026, 4, 20),
        event_id=1,
    )
    approved = _dividend(
        known_at=date(2026, 6, 25),
        record_date=date(2026, 7, 10),
        version=2,
        status=DividendStatus.APPROVED,
        amount=34.0,
        announcement_date=date(2026, 6, 25),
        event_id=2,
    )
    events = [recommended, approved]

    before_any = pit_rules.latest_dividend_state(events, date(2026, 4, 1))
    assert before_any.is_known is False
    assert before_any.status is DividendStatus.UNKNOWN

    after_recommendation = pit_rules.latest_dividend_state(events, date(2026, 5, 1))
    assert after_recommendation.status is DividendStatus.RECOMMENDED
    assert after_recommendation.amount_per_share == 30.0

    after_approval = pit_rules.latest_dividend_state(events, date(2026, 6, 30))
    assert after_approval.status is DividendStatus.APPROVED
    assert after_approval.amount_per_share == 34.0
    assert after_approval.version == 2


def test_future_record_date_is_visible_only_through_a_disclosed_announcement() -> None:
    announced = _dividend(
        known_at=date(2026, 4, 20), record_date=date(2026, 7, 10), announcement_date=date(2026, 4, 20)
    )

    # Announced: a future record date is legitimate knowledge.
    upcoming = pit_rules.next_upcoming_dividend([announced], date(2026, 5, 1))
    assert upcoming is not None
    assert upcoming.record_date == date(2026, 7, 10)
    assert upcoming.record_date_is_future is True

    # Not yet announced: the same future record date must stay invisible.
    assert pit_rules.next_upcoming_dividend([announced], date(2026, 4, 19)) is None
    assert pit_rules.visible_dividend_events([announced], date(2026, 4, 19)) == ()


def test_cancelled_dividend_is_not_reported_as_upcoming() -> None:
    announced = _dividend(known_at=date(2026, 4, 20), record_date=date(2026, 7, 10), event_id=1)
    cancelled = _dividend(
        known_at=date(2026, 5, 5),
        record_date=date(2026, 7, 10),
        version=2,
        status=DividendStatus.CANCELLED,
        amount=None,
        event_id=2,
    )

    assert pit_rules.next_upcoming_dividend([announced, cancelled], date(2026, 5, 1)) is not None
    assert pit_rules.next_upcoming_dividend([announced, cancelled], date(2026, 5, 6)) is None


def test_past_payout_is_not_upcoming_but_stays_the_latest_known_state() -> None:
    paid = _dividend(
        known_at=date(2026, 4, 20),
        record_date=date(2026, 5, 10),
        status=DividendStatus.PAID,
        event_id=1,
    )

    assert pit_rules.next_upcoming_dividend([paid], date(2026, 6, 1)) is None
    state = pit_rules.latest_dividend_state([paid], date(2026, 6, 1))
    assert state.is_known is True
    assert state.status is DividendStatus.PAID
