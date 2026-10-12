"""Focused tests for IntelligenceSnapshotBuilder (honest UNKNOWN composition)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.modules.intelligence.application.snapshot_builder import (
    EXPECTED_MODELS,
    IntelligenceSnapshotBuilder,
    build_intelligence_snapshot,
)
from app.modules.intelligence.contracts.committee import CommitteeDecisionV1
from app.modules.intelligence.contracts.risk import RiskAssessmentV1
from app.modules.intelligence.contracts.signal import SignalOutputV1


def test_builder_emits_unknown_not_neutral_when_unwired() -> None:
    instrument = SimpleNamespace(id=42, symbol="SBER", name="Sberbank")
    snap = build_intelligence_snapshot(
        instrument=instrument,
        instrument_id=42,
        as_of=date(2026, 10, 1),
    )
    assert snap.schema == "IntelligenceSnapshotV1"
    assert snap.instrument_id == 42
    assert snap.symbol == "SBER"
    assert len(snap.signals) == len(EXPECTED_MODELS)
    assert all(s.state == "UNKNOWN" for s in snap.signals)
    assert "NEUTRAL" not in {s.state for s in snap.signals}
    assert snap.committee is not None
    assert snap.committee.advisory_state == "ABSTAIN"
    assert snap.committee.what_would_change_decision
    assert snap.risk is not None
    assert snap.risk.risk_state == "UNKNOWN"
    assert snap.fundamentals_summary["status"] == "UNKNOWN"
    assert snap.macro_summary["status"] == "UNKNOWN"
    assert snap.intraday_summary["coverage_status"] == "UNKNOWN"
    assert snap.production_isolation["persist_registry"] is False
    assert snap.production_isolation["broker_execution"] is False
    coverage_statuses = {c.domain: c.status for c in snap.coverage}
    assert coverage_statuses["technical"] == "UNKNOWN"
    assert coverage_statuses["risk"] == "UNKNOWN"
    assert snap.recent_events == ()


def test_builder_accepts_injected_signals() -> None:
    instrument = SimpleNamespace(id=7, symbol="GAZP", name="Gazprom")
    signal = SignalOutputV1(
        model_id="TechnicalModelV1",
        model_version="1",
        semantic="TECHNICAL",
        instrument_id=7,
        as_of=date(2026, 10, 1),
        known_at=date(2026, 10, 1),
        horizon="20d",
        state="POSITIVE",
        score=0.3,
        confidence=0.4,
        confidence_semantic="EVIDENCE_COMPLETENESS",
    )
    snap = IntelligenceSnapshotBuilder().build(
        instrument=instrument,
        instrument_id=7,
        as_of=date(2026, 10, 1),
        signals=(signal,),
    )
    assert len(snap.signals) == 1
    assert snap.signals[0].state == "POSITIVE"
    tech = next(c for c in snap.coverage if c.domain == "technical")
    assert tech.status == "READY"


def test_recent_events_lead_with_accepted_events_and_keep_unknown_distinct() -> None:
    """PIT-visible IntelligenceEvent rows precede unscored source documents."""
    as_of = date(2026, 10, 1)
    documents = [
        _doc(10, instrument_id=42, known_at=_dt(2026, 10, 1, 18), basis="ticker_exact", title="Profit warning"),
        _doc(11, instrument_id=42, known_at=_dt(2026, 10, 1, 12), basis="issuer_name", title="Quiet update"),
        _doc(12, instrument_id=42, known_at=_dt(2026, 9, 20, 9), basis="alias", title="Unclear filing"),
        _doc(13, instrument_id=42, known_at=_dt(2026, 9, 10, 9), basis="manual", title="Abstain note"),
        _doc(14, instrument_id=42, known_at=_dt(2026, 9, 1, 9), basis="headline_only", title="Bare headline"),
        _doc(15, instrument_id=42, known_at=_dt(2026, 10, 2, 1), basis="future_basis", title="Tomorrow"),
        _doc(16, instrument_id=7, known_at=_dt(2026, 9, 1, 9), basis="other", title="Other name"),
    ]
    events = [
        _evt(
            1,
            instrument_id=42,
            source_document_id=12,
            known_at=_dt(2026, 9, 20, 9),
            direction="unknown",
            materiality="UNKNOWN",
            event_type="OTHER",
            title="Unclear filing",
        ),
        _evt(
            2,
            instrument_id=42,
            source_document_id=10,
            known_at=_dt(2026, 10, 1, 18),
            direction="NEGATIVE",
            materiality="HIGH",
            event_type="EARNINGS",
            title="Profit warning",
        ),
        _evt(
            3,
            instrument_id=42,
            source_document_id=13,
            known_at=_dt(2026, 9, 10, 9),
            direction="ABSTAIN",
            materiality="LOW",
            event_type="GUIDANCE",
            title="Abstain note",
        ),
        _evt(
            4,
            instrument_id=42,
            source_document_id=11,
            known_at=_dt(2026, 10, 1, 12),
            direction="NEUTRAL",
            materiality="MEDIUM",
            event_type="OPERATIONAL",
            title="Quiet update",
        ),
        _evt(
            5,
            instrument_id=42,
            source_document_id=15,
            known_at=_dt(2026, 10, 2, 1),
            direction="POSITIVE",
            materiality="HIGH",
            event_type="DIVIDEND",
            title="Tomorrow",
        ),
        _evt(
            6,
            instrument_id=99,
            source_document_id=16,
            known_at=_dt(2026, 9, 1, 9),
            direction="NEGATIVE",
            materiality="HIGH",
            event_type="SANCTIONS",
            title="Other name",
        ),
    ]
    session = _EventSession(events, documents)
    snap = IntelligenceSnapshotBuilder().build(
        instrument=SimpleNamespace(id=42, symbol="SBER", name="Sberbank"),
        instrument_id=42,
        as_of=as_of,
        session=session,
        signals=(),
        committee=_committee(as_of),
        risk=_risk(as_of),
        fundamentals_summary={"status": "UNKNOWN", "issuer_kind": "UNKNOWN"},
        macro_summary={"status": "UNKNOWN"},
        knowledge_evaluations=(),
        intraday_summary={"coverage_status": "UNKNOWN"},
    )
    rows = snap.recent_events
    assert [row["evidence_role"] for row in rows] == [
        "extracted_event",
        "extracted_event",
        "extracted_event",
        "extracted_event",
        "unscored_news",
    ]
    assert [row["direction"] for row in rows] == ["NEGATIVE", "NEUTRAL", "UNKNOWN", "ABSTAIN", None]
    assert rows[0]["materiality"] == "HIGH"
    assert rows[0]["event_type"] == "EARNINGS"
    assert rows[0]["provider"] == "interfax"
    assert rows[0]["title"] == "Profit warning"
    assert rows[0]["source_document_id"] == 10
    assert rows[0]["mapping_basis"] == "ticker_exact"
    assert rows[0]["published_at"] == _dt(2026, 9, 30, 8).isoformat()
    assert rows[0]["known_at"] == _dt(2026, 10, 1, 18).isoformat()
    assert rows[2]["direction"] == "UNKNOWN"
    assert rows[3]["direction"] == "ABSTAIN"
    assert "certainty" not in rows[0]
    assert "confidence" not in rows[0]
    unscored = rows[4]
    assert unscored["evidence_role"] == "unscored_news"
    assert unscored["direction"] is None
    assert unscored["event_type"] is None
    assert unscored["title"] == "Bare headline"
    assert unscored["provider"] == "interfax"
    assert unscored["source_document_id"] == 14
    assert unscored["mapping_basis"] == "headline_only"
    assert unscored["historical_eligible"] is False
    assert all(row["title"] != "Tomorrow" for row in rows)
    assert all(row["title"] != "Other name" for row in rows)
    event_sql = str(session.statements[0])
    document_sql = str(session.statements[1])
    assert "known_at" in event_sql
    assert "known_at" in document_sql


class _EventSession:
    def __init__(self, events: list[SimpleNamespace], documents: list[SimpleNamespace]) -> None:
        self.events = events
        self.documents = documents
        self.statements: list[object] = []

    def scalars(self, stmt: object) -> SimpleNamespace:
        self.statements.append(stmt)
        entity = stmt.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        name = getattr(entity, "__name__", "")
        rows = self.events if name == "IntelligenceEvent" else self.documents
        return SimpleNamespace(all=lambda: list(rows))


def _dt(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=UTC)


def _doc(
    doc_id: int,
    *,
    instrument_id: int,
    known_at: datetime,
    basis: str,
    title: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=doc_id,
        instrument_id=instrument_id,
        provider="interfax",
        title=title,
        canonical_url=f"https://example.test/{doc_id}",
        published_at=datetime(2026, 9, 30, 8, 0, tzinfo=UTC),
        observed_at=datetime(2026, 9, 30, 9, 0, tzinfo=UTC),
        known_at=known_at,
        mapping_basis=basis,
    )


def _evt(
    event_id: int,
    *,
    instrument_id: int,
    source_document_id: int,
    known_at: datetime,
    direction: str,
    materiality: str,
    event_type: str,
    title: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=event_id,
        instrument_id=instrument_id,
        source_document_id=source_document_id,
        event_type=event_type,
        materiality=materiality,
        direction=direction,
        title=title,
        known_at=known_at,
        published_at=datetime(2026, 9, 30, 8, 0, tzinfo=UTC),
        observed_at=datetime(2026, 9, 30, 9, 0, tzinfo=UTC),
        payload={"confidence": 0.2, "sentiment": "bad"},
    )


def _committee(as_of: date) -> CommitteeDecisionV1:
    return CommitteeDecisionV1(
        as_of=as_of,
        instrument_id=42,
        advisory_state="ABSTAIN",
        confidence=None,
        consensus_strength=None,
        disagreement_score=None,
        independent_model_votes=(),
    )


def _risk(as_of: date) -> RiskAssessmentV1:
    return RiskAssessmentV1(as_of=as_of, instrument_id=42, risk_state="UNKNOWN")
