"""Point-in-time selection rules for fundamentals and events.

Pure functions over domain records. These rules are the single place that decides what
is knowable at a decision time ``t``; the application layer only loads rows and delegates.

Two hard rules:

1. A record is visible at ``as_of`` only when ``known_at <= as_of``.
2. A future economic date (record date, payment date, effective date) is allowed —
   an announced future event is legitimate knowledge — but only through a record whose
   ``known_at`` already passed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from app.modules.fundamentals.domain.types import (
    CorporateEventRef,
    DividendEventRef,
    DividendState,
    DividendStatus,
    ReportRef,
    ReportStatus,
)


def is_visible(known_at: date | None, as_of: date) -> bool:
    """No known_at means no provable availability, so the record is never visible."""
    return known_at is not None and known_at <= as_of


def visible_reports(reports: Iterable[ReportRef], as_of: date) -> tuple[ReportRef, ...]:
    return tuple(
        report
        for report in reports
        if is_visible(report.known_at, as_of) and report.status is not ReportStatus.REJECTED
    )


def effective_report_for_period(
    reports: Iterable[ReportRef], as_of: date, period_key: tuple[str, str, date]
) -> ReportRef | None:
    """Restatement resolution: within one period the latest disclosed version wins."""
    candidates = [r for r in visible_reports(reports, as_of) if r.period_key == period_key]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r.known_at, r.report_version))


def latest_report(reports: Iterable[ReportRef], as_of: date) -> ReportRef | None:
    """Newest reported period that is already disclosed, restatement-resolved."""
    candidates = visible_reports(reports, as_of)
    if not candidates:
        return None
    newest_period = max(r.period_end for r in candidates)
    in_period = [r for r in candidates if r.period_end == newest_period]
    return max(in_period, key=lambda r: (r.known_at, r.report_version))


def visible_dividend_events(
    events: Iterable[DividendEventRef], as_of: date
) -> tuple[DividendEventRef, ...]:
    return tuple(event for event in events if is_visible(event.known_at, as_of))


def group_dividend_series(
    events: Iterable[DividendEventRef],
) -> dict[tuple[int, int, date | None], list[DividendEventRef]]:
    series: dict[tuple[int, int, date | None], list[DividendEventRef]] = {}
    for event in events:
        series.setdefault(event.series_key, []).append(event)
    return series


def resolve_series_state(
    series_events: Sequence[DividendEventRef], as_of: date
) -> DividendState:
    """Latest disclosed version of one payout series at ``as_of``."""
    candidates = visible_dividend_events(series_events, as_of)
    if not candidates:
        return DividendState(as_of=as_of, is_known=False)
    winner = max(candidates, key=lambda e: (e.known_at, e.version))
    return DividendState(
        as_of=as_of,
        is_known=True,
        status=winner.status,
        event_id=winner.event_id,
        known_at=winner.known_at,
        version=winner.version,
        amount_per_share=winner.amount_per_share,
        currency=winner.currency,
        announcement_date=winner.announcement_date,
        record_date=winner.record_date,
        ex_date=winner.ex_date,
        payment_date=winner.payment_date,
    )


def dividend_states_as_of(
    events: Iterable[DividendEventRef], as_of: date
) -> tuple[DividendState, ...]:
    """One resolved state per payout series, oldest disclosure first."""
    states = [
        state
        for series in group_dividend_series(events).values()
        if (state := resolve_series_state(series, as_of)).is_known
    ]
    states.sort(key=lambda s: (s.known_at or as_of, s.event_id or 0))
    return tuple(states)


def latest_dividend_state(events: Iterable[DividendEventRef], as_of: date) -> DividendState:
    """Most recently disclosed payout series, regardless of whether it already paid."""
    states = dividend_states_as_of(events, as_of)
    if not states:
        return DividendState(as_of=as_of, is_known=False)
    return states[-1]


def next_upcoming_dividend(
    events: Iterable[DividendEventRef], as_of: date
) -> DividendState | None:
    """Nearest announced record date at or after ``as_of``. Cancellations are excluded."""
    upcoming = [
        state
        for state in dividend_states_as_of(events, as_of)
        if state.record_date is not None
        and state.record_date >= as_of
        and state.status is not DividendStatus.CANCELLED
    ]
    if not upcoming:
        return None
    return min(upcoming, key=lambda s: s.record_date or as_of)


def visible_corporate_events(
    events: Iterable[CorporateEventRef], as_of: date
) -> tuple[CorporateEventRef, ...]:
    return tuple(event for event in events if is_visible(event.known_at, as_of))


def last_corporate_event(
    events: Iterable[CorporateEventRef], as_of: date
) -> CorporateEventRef | None:
    candidates = [e for e in visible_corporate_events(events, as_of) if e.event_date <= as_of]
    if not candidates:
        return None
    return max(candidates, key=lambda e: (e.event_date, e.known_at))


def days_between(earlier: date, later: date) -> int:
    return (later - earlier).days
