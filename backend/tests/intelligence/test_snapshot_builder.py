"""Focused tests for IntelligenceSnapshotBuilder (honest UNKNOWN composition)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.modules.intelligence.application.snapshot_builder import (
    EXPECTED_MODELS,
    IntelligenceSnapshotBuilder,
    build_intelligence_snapshot,
)
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
