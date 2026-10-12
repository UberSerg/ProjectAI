"""Append-only extractor history and prospective coverage without future known_at."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.intelligence.extraction.deterministic import DETERMINISTIC_EXTRACTOR_VERSION
from app.modules.intelligence.extraction.refresh import refresh_extract_events
from app.modules.intelligence.news.models import ExtractedFact, IntelligenceEvent, IntelligenceSourceDocument
from app.modules.intelligence.prospective.report import STATEMENT, build_prospective_coverage_report
from app.modules.intelligence.signals.event import MODEL_ID as EVENT_MODEL_ID

_AS_OF = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_FUTURE_KNOWN_AT = _AS_OF + timedelta(seconds=1)
_SECOND_EXTRACTOR_VERSION = "extractor_v2_not_deterministic"


def test_second_extractor_version_appends_and_coverage_excludes_future_known_at(
    core_db: Session,
) -> None:
    instrument = _instrument(core_db)
    baseline = build_prospective_coverage_report(core_db, _AS_OF)
    positive = _document(
        core_db,
        text="The board increased the dividend to 35 RUB per share for 2025.",
        known_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        instrument_id=instrument.id,
    )
    unknown = _document(
        core_db,
        text="The board declared a dividend.",
        known_at=datetime(2026, 5, 2, 10, 0, tzinfo=UTC),
        instrument_id=instrument.id,
    )
    unmapped = _document(
        core_db,
        text="The board increased the dividend to 7 RUB per share for 2024.",
        known_at=datetime(2026, 5, 1, 11, 0, tzinfo=UTC),
        instrument_id=None,
    )

    refresh_extract_events(
        core_db,
        {
            "dry_run": False,
            "live_fetch": True,
            "as_of": _AS_OF,
            "document_ids": [positive.id, unknown.id, unmapped.id],
        },
    )
    original = _only_version(core_db, positive.id, DETERMINISTIC_EXTRACTOR_VERSION)
    before = _fact_snapshot(original)
    core_db.add(
        ExtractedFact(
            source_document_id=positive.id,
            extractor_version=_SECOND_EXTRACTOR_VERSION,
            event_type=original.event_type,
            materiality="LOW",
            direction="NEGATIVE",
            affected_horizon="unspecified",
            claim={"schema": "SecondExtractorClaim", "note": "append-only history"},
            evidence_fragment="second extractor evidence",
            confidence=0.1,
            status="ACCEPTED",
        )
    )
    core_db.flush()

    again = refresh_extract_events(
        core_db,
        {
            "dry_run": False,
            "live_fetch": True,
            "as_of": _AS_OF,
            "document_ids": [positive.id],
        },
    )
    assert again["facts_inserted"] == 0
    core_db.expire_all()
    kept = _only_version(core_db, positive.id, DETERMINISTIC_EXTRACTOR_VERSION)
    second = _only_version(core_db, positive.id, _SECOND_EXTRACTOR_VERSION)
    assert _fact_snapshot(kept) == before
    assert kept.extractor_version == DETERMINISTIC_EXTRACTOR_VERSION
    assert second.id != kept.id
    assert second.direction == "NEGATIVE"
    assert second.claim["note"] == "append-only history"

    after_past = build_prospective_coverage_report(core_db, _AS_OF)
    assert after_past["interpretation"] == "coverage"
    assert after_past["measures_accuracy"] is False
    assert after_past["statement"] == STATEMENT
    assert "coverage" in after_past["statement"]
    assert "not accuracy" in after_past["statement"]
    assert "win_rate" not in after_past
    assert after_past["documents_observed"] == baseline["documents_observed"] + 3
    assert after_past["documents_company_mapped"] == baseline["documents_company_mapped"] + 2
    assert after_past["events_extracted"] == baseline["events_extracted"] + 2
    assert after_past["directional_events"] == baseline["directional_events"] + 1
    assert after_past["unknown_direction_events"] == baseline["unknown_direction_events"] + 1
    assert _day_delta(baseline, after_past, "2026-05-01", "documents_observed") == 2
    assert _day_delta(baseline, after_past, "2026-05-01", "documents_company_mapped") == 1
    assert _day_delta(baseline, after_past, "2026-05-01", "directional_events") == 1
    assert _day_delta(baseline, after_past, "2026-05-02", "unknown_direction_events") == 1
    assert _day_delta(baseline, after_past, "2026-06-01", "documents_observed") == 0

    future = _document(
        core_db,
        text="The board increased the dividend to 99 RUB per share for 2026.",
        known_at=_FUTURE_KNOWN_AT,
        instrument_id=instrument.id,
    )
    core_db.add(
        IntelligenceEvent(
            instrument_id=instrument.id,
            event_type="DIVIDEND",
            materiality="MEDIUM",
            direction="POSITIVE",
            title="future dividend",
            known_at=_FUTURE_KNOWN_AT,
            published_at=_FUTURE_KNOWN_AT,
            observed_at=_FUTURE_KNOWN_AT,
            source_document_id=future.id,
            payload={"extractor_version": DETERMINISTIC_EXTRACTOR_VERSION},
        )
    )
    _insert_signal(
        core_db,
        instrument_id=instrument.id,
        model_id=EVENT_MODEL_ID,
        state="POSITIVE",
        as_of_day="2026-05-01",
        known_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        horizon="past-positive",
    )
    _insert_signal(
        core_db,
        instrument_id=instrument.id,
        model_id=EVENT_MODEL_ID,
        state="ABSTAIN",
        as_of_day="2026-05-02",
        known_at=datetime(2026, 5, 2, 10, 0, tzinfo=UTC),
        horizon="past-abstain",
    )
    _insert_signal(
        core_db,
        instrument_id=instrument.id,
        model_id=EVENT_MODEL_ID,
        state="UNKNOWN",
        as_of_day="2026-05-03",
        known_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
        horizon="past-unknown",
    )
    _insert_signal(
        core_db,
        instrument_id=instrument.id,
        model_id=EVENT_MODEL_ID,
        state="NEGATIVE",
        as_of_day="2026-06-02",
        known_at=_FUTURE_KNOWN_AT,
        horizon="future-negative",
    )
    _insert_signal(
        core_db,
        instrument_id=instrument.id,
        model_id=EVENT_MODEL_ID,
        state="POSITIVE",
        as_of_day="2026-05-04",
        known_at=None,
        horizon="null-known-at",
    )
    _insert_signal(
        core_db,
        instrument_id=instrument.id,
        model_id="TechnicalModelV1",
        state="POSITIVE",
        as_of_day="2026-05-01",
        known_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        horizon="other-model",
    )
    core_db.execute(
        text(
            """
            INSERT INTO intelligence.committee_decisions (
                instrument_id, as_of, advisory_state, committee_policy_version, payload
            ) VALUES (
                :instrument_id, DATE '2020-01-01', 'HOLD', :policy, CAST(:payload AS jsonb)
            )
            """
        ),
        {
            "instrument_id": instrument.id,
            "policy": f"test-policy-{uuid4().hex}",
            "payload": "{}",
        },
    )
    core_db.flush()

    covered = build_prospective_coverage_report(core_db, _AS_OF)
    assert covered["documents_observed"] == after_past["documents_observed"]
    assert covered["documents_company_mapped"] == after_past["documents_company_mapped"]
    assert covered["events_extracted"] == after_past["events_extracted"]
    assert covered["directional_events"] == after_past["directional_events"]
    assert covered["unknown_direction_events"] == after_past["unknown_direction_events"]
    assert _day_delta(after_past, covered, "2026-06-01", "events_extracted") == 0
    assert covered["event_model_source"] == "intelligence.signal_outputs"
    assert covered["event_model_non_unknown"] == after_past["event_model_non_unknown"] + 2
    assert covered["committee_snapshots"] is None
    assert covered["committee_snapshots_reason"] == "no_known_at_column"
    assert any("committee_decisions has no known_at" in note for note in covered["limitations"])

    widened = build_prospective_coverage_report(core_db, _FUTURE_KNOWN_AT)
    assert widened["documents_observed"] == covered["documents_observed"] + 1
    assert widened["events_extracted"] == covered["events_extracted"] + 1
    assert widened["event_model_non_unknown"] == covered["event_model_non_unknown"] + 1
    assert widened["committee_snapshots"] is None


def _fact_snapshot(row: ExtractedFact) -> dict:
    return {
        "id": row.id,
        "source_document_id": row.source_document_id,
        "extractor_version": row.extractor_version,
        "event_type": row.event_type,
        "materiality": row.materiality,
        "direction": row.direction,
        "affected_horizon": row.affected_horizon,
        "claim": json.loads(json.dumps(row.claim)),
        "evidence_fragment": row.evidence_fragment,
        "confidence": row.confidence,
        "status": row.status,
    }


def _only_version(session: Session, document_id: int, extractor_version: str) -> ExtractedFact:
    rows = list(
        session.scalars(
            select(ExtractedFact).where(
                ExtractedFact.source_document_id == document_id,
                ExtractedFact.extractor_version == extractor_version,
            )
        ).all()
    )
    assert len(rows) == 1
    return rows[0]


def _day_count(report: dict, day: str, field: str) -> int:
    for row in report["coverage_by_day"]:
        if row["day"] == day:
            return int(row[field])
    return 0


def _day_delta(before: dict, after: dict, day: str, field: str) -> int:
    return _day_count(after, day, field) - _day_count(before, day, field)


def _insert_signal(
    session: Session,
    *,
    instrument_id: int,
    model_id: str,
    state: str,
    as_of_day: str,
    known_at: datetime | None,
    horizon: str,
) -> None:
    session.execute(
        text(
            """
            INSERT INTO intelligence.signal_outputs (
                model_id, model_version, semantic, instrument_id, as_of, known_at,
                horizon, state
            ) VALUES (
                :model_id, '1', 'EVENT', :instrument_id, CAST(:as_of AS date), :known_at,
                :horizon, :state
            )
            """
        ),
        {
            "model_id": model_id,
            "instrument_id": instrument_id,
            "as_of": as_of_day,
            "known_at": known_at,
            "horizon": horizon,
            "state": state,
        },
    )


def _instrument(session: Session) -> Instrument:
    row = Instrument(
        symbol=f"IAF{uuid4().hex[:8].upper()}",
        name="IA F prospective",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
    )
    session.add(row)
    session.flush()
    return row


def _document(
    session: Session,
    *,
    text: str,
    known_at: datetime,
    instrument_id: int | None,
) -> IntelligenceSourceDocument:
    row = IntelligenceSourceDocument(
        document_key=f"ia-f-{uuid4().hex}",
        provider="ia-f-test",
        source_type="UNIT_TEST",
        title="unit",
        published_at=datetime(2026, 5, 1, 8, 0, tzinfo=UTC),
        observed_at=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
        known_at=known_at,
        content_hash=uuid4().hex,
        language="en",
        instrument_id=instrument_id,
        parse_status="RAW",
        raw_text=text,
        metadata_={},
        revision=1,
    )
    session.add(row)
    session.flush()
    return row
