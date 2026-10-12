"""Read-only prospective coverage of persisted intelligence rows.

Counts rows whose ``known_at`` is at or before an as-of timestamp. The result is
coverage of what was stored, not accuracy, a win rate, or a backtest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Date, case, cast, func, select, text
from sqlalchemy.orm import Session

from app.modules.intelligence.news.models import IntelligenceEvent, IntelligenceSourceDocument
from app.modules.intelligence.signals.event import MODEL_ID as EVENT_MODEL_ID

SCHEMA = "ProspectiveEventCoverageV1"
INTERPRETATION = "coverage"
STATEMENT = (
    "This report is coverage of persisted rows with known_at <= as_of, not accuracy."
)
DIRECTIONAL_DIRECTIONS = ("POSITIVE", "NEGATIVE", "NEUTRAL")
_SIGNAL_TABLE = "signal_outputs"
_COMMITTEE_TABLE = "committee_decisions"


@dataclass(frozen=True, slots=True)
class _OptionalCount:
    count: int | None
    source: str | None
    reason: str | None


def build_prospective_coverage_report(session: Session, as_of: datetime) -> dict[str, Any]:
    """Count persisted coverage visible at ``as_of``. Does not write."""
    cutoff = _require_aware_timestamp(as_of)
    documents_observed = _count(
        session,
        IntelligenceSourceDocument,
        IntelligenceSourceDocument.known_at <= cutoff,
    )
    documents_company_mapped = _count(
        session,
        IntelligenceSourceDocument,
        IntelligenceSourceDocument.known_at <= cutoff,
        IntelligenceSourceDocument.instrument_id.is_not(None),
    )
    events_extracted = _count(
        session,
        IntelligenceEvent,
        IntelligenceEvent.known_at <= cutoff,
    )
    directional_events = _count(
        session,
        IntelligenceEvent,
        IntelligenceEvent.known_at <= cutoff,
        IntelligenceEvent.direction.in_(DIRECTIONAL_DIRECTIONS),
    )
    unknown_direction_events = _count(
        session,
        IntelligenceEvent,
        IntelligenceEvent.known_at <= cutoff,
        IntelligenceEvent.direction == "UNKNOWN",
    )
    event_model = _event_model_non_unknown(session, cutoff)
    committee = _committee_snapshots(session, cutoff)
    return {
        "schema": SCHEMA,
        "interpretation": INTERPRETATION,
        "measures_accuracy": False,
        "statement": STATEMENT,
        "as_of": cutoff.isoformat(),
        "known_at_predicate": "known_at <= as_of",
        "documents_observed": documents_observed,
        "documents_company_mapped": documents_company_mapped,
        "events_extracted": events_extracted,
        "directional_events": directional_events,
        "unknown_direction_events": unknown_direction_events,
        "event_model_non_unknown": event_model.count,
        "event_model_source": event_model.source,
        "event_model_reason": event_model.reason,
        "committee_snapshots": committee.count,
        "committee_snapshot_source": committee.source,
        "committee_snapshots_reason": committee.reason,
        "coverage_by_day": _coverage_by_day(session, cutoff),
        "limitations": _limitations(event_model, committee),
    }


def _require_aware_timestamp(as_of: datetime) -> datetime:
    if not isinstance(as_of, datetime):
        raise TypeError("as_of must be a timezone-aware datetime")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware; known_at is not backdated to a bare date")
    return as_of.astimezone(UTC)


def _count(session: Session, model: type, *criteria: Any) -> int:
    stmt = select(func.count()).select_from(model).where(*criteria)
    return int(session.scalar(stmt) or 0)


def _coverage_by_day(session: Session, cutoff: datetime) -> list[dict[str, Any]]:
    """UTC calendar days of document and event ``known_at`` inside the window."""
    buckets: dict[date, dict[str, Any]] = {}

    doc_day = cast(func.timezone("UTC", IntelligenceSourceDocument.known_at), Date)
    document_rows = session.execute(
        select(
            doc_day.label("day"),
            func.count().label("documents_observed"),
            func.count(IntelligenceSourceDocument.instrument_id).label("documents_company_mapped"),
        )
        .where(IntelligenceSourceDocument.known_at <= cutoff)
        .group_by(doc_day)
    ).all()
    for row in document_rows:
        bucket = _bucket(buckets, row.day)
        bucket["documents_observed"] = int(row.documents_observed or 0)
        bucket["documents_company_mapped"] = int(row.documents_company_mapped or 0)

    event_day = cast(func.timezone("UTC", IntelligenceEvent.known_at), Date)
    directional = case(
        (IntelligenceEvent.direction.in_(DIRECTIONAL_DIRECTIONS), 1),
        else_=0,
    )
    unknown = case((IntelligenceEvent.direction == "UNKNOWN", 1), else_=0)
    event_rows = session.execute(
        select(
            event_day.label("day"),
            func.count().label("events_extracted"),
            func.coalesce(func.sum(directional), 0).label("directional_events"),
            func.coalesce(func.sum(unknown), 0).label("unknown_direction_events"),
        )
        .where(IntelligenceEvent.known_at <= cutoff)
        .group_by(event_day)
    ).all()
    for row in event_rows:
        bucket = _bucket(buckets, row.day)
        bucket["events_extracted"] = int(row.events_extracted or 0)
        bucket["directional_events"] = int(row.directional_events or 0)
        bucket["unknown_direction_events"] = int(row.unknown_direction_events or 0)

    return [buckets[day] for day in sorted(buckets)]


def _bucket(buckets: dict[date, dict[str, Any]], raw_day: date | datetime) -> dict[str, Any]:
    day = raw_day.date() if isinstance(raw_day, datetime) else raw_day
    bucket = buckets.get(day)
    if bucket is None:
        bucket = {
            "day": day.isoformat(),
            "documents_observed": 0,
            "documents_company_mapped": 0,
            "events_extracted": 0,
            "directional_events": 0,
            "unknown_direction_events": 0,
        }
        buckets[day] = bucket
    return bucket


def _event_model_non_unknown(session: Session, cutoff: datetime) -> _OptionalCount:
    """EventModel rows already stored on ``signal_outputs``. No new store."""
    if not _table_exists(session, _SIGNAL_TABLE):
        return _OptionalCount(None, None, "table_absent")
    if not _column_exists(session, _SIGNAL_TABLE, "known_at"):
        return _OptionalCount(None, None, "no_known_at_column")
    count = session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM intelligence.signal_outputs
            WHERE model_id = :model_id
              AND state <> 'UNKNOWN'
              AND known_at IS NOT NULL
              AND known_at <= :as_of
            """
        ),
        {"model_id": EVENT_MODEL_ID, "as_of": cutoff},
    ).scalar_one()
    return _OptionalCount(int(count or 0), "intelligence.signal_outputs", "counted")


def _committee_snapshots(session: Session, cutoff: datetime) -> _OptionalCount:
    """Committee rows are counted only when the table itself stores ``known_at``.

    ``committee_decisions.as_of`` and ``created_at`` are not substitutes.
    ``refresh_committee`` computes decisions on read and does not persist them.
    """
    if not _table_exists(session, _COMMITTEE_TABLE):
        return _OptionalCount(None, None, "table_absent")
    if not _column_exists(session, _COMMITTEE_TABLE, "known_at"):
        return _OptionalCount(None, None, "no_known_at_column")
    count = session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM intelligence.committee_decisions
            WHERE known_at IS NOT NULL
              AND known_at <= :as_of
            """
        ),
        {"as_of": cutoff},
    ).scalar_one()
    return _OptionalCount(int(count or 0), "intelligence.committee_decisions", "counted")


def _limitations(event_model: _OptionalCount, committee: _OptionalCount) -> list[str]:
    notes = [
        "Coverage only: row counts are not accuracy, win rate, or a backtest.",
        "known_at is not backdated. Rows with a later known_at stay outside the window.",
        "extracted_facts have no known_at; a new extractor_version is a new fact row.",
        "MIXED is neither a directional nor an unknown-direction event.",
        "signal outputs are computed on read and are not written by refresh_run_models.",
        "committee decisions are computed on read and are not written by refresh_committee.",
    ]
    if event_model.reason == "counted":
        notes.append(
            "EventModel non-UNKNOWN counts read intelligence.signal_outputs "
            "where known_at is present and known_at <= as_of."
        )
    elif event_model.reason == "table_absent":
        notes.append("intelligence.signal_outputs is absent; EventModel outputs are not counted.")
    elif event_model.reason == "no_known_at_column":
        notes.append("intelligence.signal_outputs has no known_at; EventModel outputs are not counted.")
    if committee.reason == "no_known_at_column":
        notes.append(
            "intelligence.committee_decisions has no known_at column; "
            "as_of and created_at are not used, so committee snapshots are omitted."
        )
    elif committee.reason == "table_absent":
        notes.append("intelligence.committee_decisions is absent; committee snapshots are not counted.")
    elif committee.reason == "counted":
        notes.append(
            "Committee snapshot counts read intelligence.committee_decisions "
            "where known_at is present and known_at <= as_of."
        )
    return notes


def _table_exists(session: Session, table_name: str) -> bool:
    if table_name not in {_SIGNAL_TABLE, _COMMITTEE_TABLE}:
        raise ValueError(f"unsupported intelligence table: {table_name}")
    qualified = f"intelligence.{table_name}"
    return bool(
        session.execute(text(f"SELECT to_regclass('{qualified}') IS NOT NULL")).scalar_one()
    )


def _column_exists(session: Session, table_name: str, column_name: str) -> bool:
    return bool(
        session.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'intelligence'
                      AND table_name = :table_name
                      AND column_name = :column_name
                )
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).scalar_one()
    )
