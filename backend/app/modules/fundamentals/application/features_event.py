"""`event_daily` v1 feature contract over corporate events and dividend disclosures.

An announced *future* date is legitimate knowledge, so `days_to_next_dividend_record_date`
may look forward — but only through a disclosure whose ``known_at`` already passed. When
an instrument has no dividend disclosures at all, the dividend features are omitted:
"unknown" is not the same as "no dividend".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fundamentals.application import pit
from app.modules.fundamentals.application.features_fundamental import LookaheadError
from app.modules.fundamentals.domain import pit_rules
from app.modules.fundamentals.domain.types import (
    EVENT_FEATURE_SET_CODE,
    EVENT_FEATURE_SET_VERSION,
    SPLIT_LOOKBACK_DAYS,
    CorporateEventRef,
    CorporateEventType,
    DividendEventRef,
    ReadinessStatus,
)
from app.modules.fundamentals.infrastructure.models import (
    CorporateEvent,
    DividendEvent,
    fundamentals_schema_ready,
)


@dataclass(frozen=True, slots=True)
class EventFeatureRow:
    as_of: date
    instrument_id: int
    feature_known_at: date
    features: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "instrument_id": self.instrument_id,
            "feature_known_at": self.feature_known_at.isoformat(),
            "features": dict(self.features),
        }


@dataclass
class EventFeatureResult:
    as_of: date
    status: str = ReadinessStatus.NOT_READY.value
    feature_set_code: str = EVENT_FEATURE_SET_CODE
    feature_set_version: int = EVENT_FEATURE_SET_VERSION
    rows: list[EventFeatureRow] = field(default_factory=list)
    instruments_considered: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "feature_set_code": self.feature_set_code,
            "feature_set_version": self.feature_set_version,
            "as_of": self.as_of.isoformat(),
            "instruments_considered": self.instruments_considered,
            "row_count": len(self.rows),
            "rows": [row.to_dict() for row in self.rows],
            "reasons": self.reasons,
        }


def build_event_features(
    as_of: date,
    *,
    instrument_id: int,
    corporate_events: Iterable[CorporateEventRef] = (),
    dividend_events: Iterable[DividendEventRef] = (),
) -> EventFeatureRow | None:
    """Pure row builder. Returns None when nothing is known for this instrument."""
    visible_events = pit_rules.visible_corporate_events(corporate_events, as_of)
    visible_dividends = pit_rules.visible_dividend_events(dividend_events, as_of)
    if not visible_events and not visible_dividends:
        return None

    features: dict[str, float] = {}
    known_at_dates: list[date] = []

    splits = [
        event
        for event in visible_events
        if event.event_type in {CorporateEventType.SPLIT, CorporateEventType.REVERSE_SPLIT}
    ]
    last_split = pit_rules.last_corporate_event(splits, as_of)
    if last_split is not None:
        features["days_since_last_split"] = float((as_of - last_split.event_date).days)
        known_at_dates.append(last_split.known_at)
    if splits:
        window_start = as_of - timedelta(days=SPLIT_LOOKBACK_DAYS)
        features["split_events_365d"] = float(
            sum(1 for event in splits if window_start <= event.event_date <= as_of)
        )
        known_at_dates.extend(event.known_at for event in splits)

    if visible_dividends:
        latest = pit_rules.latest_dividend_state(visible_dividends, as_of)
        if latest.is_known and latest.known_at is not None:
            features["days_since_last_dividend_disclosure"] = float(
                (as_of - latest.known_at).days
            )
            known_at_dates.append(latest.known_at)
            if latest.amount_per_share is not None:
                features["last_disclosed_dividend_per_share"] = float(latest.amount_per_share)
        upcoming = pit_rules.next_upcoming_dividend(visible_dividends, as_of)
        features["has_known_upcoming_dividend"] = 1.0 if upcoming is not None else 0.0
        if upcoming is not None and upcoming.record_date is not None:
            features["days_to_next_dividend_record_date"] = float(
                (upcoming.record_date - as_of).days
            )
            if upcoming.known_at is not None:
                known_at_dates.append(upcoming.known_at)

    if not features or not known_at_dates:
        return None
    feature_known_at = max(known_at_dates)
    if feature_known_at > as_of:
        raise LookaheadError(
            f"event feature known_at {feature_known_at} is after sample date {as_of}"
        )
    return EventFeatureRow(
        as_of=as_of,
        instrument_id=instrument_id,
        feature_known_at=feature_known_at,
        features=features,
    )


def _instrument_ids_with_events(session: Session) -> list[int]:
    event_ids = session.execute(
        select(CorporateEvent.instrument_id)
        .where(CorporateEvent.instrument_id.is_not(None))
        .distinct()
    ).scalars()
    dividend_ids = session.execute(
        select(DividendEvent.instrument_id)
        .where(DividendEvent.instrument_id.is_not(None))
        .distinct()
    ).scalars()
    return sorted({int(i) for i in event_ids} | {int(i) for i in dividend_ids})


def materialize_event_daily(
    session: Session,
    as_of: date,
    *,
    instrument_ids: Sequence[int] | None = None,
) -> EventFeatureResult:
    """Build `event_daily` rows for one sample date from whatever is genuinely known."""
    result = EventFeatureResult(as_of=as_of)
    if not fundamentals_schema_ready(session):
        result.reasons.append("fundamentals schema missing; apply alembic 20260905_0018")
        return result

    events_total = int(
        session.execute(select(func.count()).select_from(CorporateEvent)).scalar_one()
    )
    dividends_total = int(
        session.execute(select(func.count()).select_from(DividendEvent)).scalar_one()
    )
    if events_total == 0 and dividends_total == 0:
        result.reasons.append("fundamentals.corporate_events and dividend_events are empty")
        return result

    candidates = _instrument_ids_with_events(session)
    if instrument_ids is not None:
        wanted = set(instrument_ids)
        candidates = [i for i in candidates if i in wanted]
    result.instruments_considered = len(candidates)

    for instrument_id in candidates:
        row = build_event_features(
            as_of,
            instrument_id=instrument_id,
            corporate_events=pit.load_visible_corporate_events(
                session, as_of, instrument_id=instrument_id
            ),
            dividend_events=pit.load_visible_dividend_events(
                session, as_of, instrument_id=instrument_id
            ),
        )
        if row is not None:
            result.rows.append(row)

    if not result.rows:
        result.reasons.append("no instrument had a visible event at as_of")
        return result
    result.status = (
        ReadinessStatus.READY.value
        if len(result.rows) == len(candidates)
        else ReadinessStatus.PARTIAL.value
    )
    return result
