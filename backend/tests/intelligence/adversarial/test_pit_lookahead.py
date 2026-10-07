"""Adversarial PIT: look-ahead leakage, revised facts, published_at after as_of."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.intelligence.contracts.provenance import (
    EvidenceRef,
    ProvenanceTimestamps,
    known_at_allows,
)
from app.modules.intelligence.contracts.signal import SignalOutputV1, abstain_signal
from app.modules.intelligence.contracts.snapshots_domain import (
    FundamentalSnapshotV1,
    SourceDocumentV1,
)
from tests.intelligence.adversarial._helpers import (
    content_hash,
    honest_known_at,
    pit_visible_docs,
    pit_visible_evidence,
)


def test_known_at_gate_blocks_future_and_missing() -> None:
    as_of = date(2026, 8, 27)
    assert known_at_allows(as_of, date(2026, 8, 27))
    assert not known_at_allows(as_of, date(2026, 8, 28))
    assert not known_at_allows(as_of, None)
    # Look-ahead by one day must never leak.
    assert not known_at_allows(as_of, as_of + timedelta(days=1))


def test_revised_fundamentals_not_visible_in_past() -> None:
    """Restatement with later known_at must not appear at earlier as_of."""
    as_of_v1 = date(2024, 6, 1)
    original = FundamentalSnapshotV1(
        instrument_id=10,
        as_of=as_of_v1,
        known_at=date(2024, 5, 15),
        period_end=date(2024, 3, 31),
        issuer_kind="INDUSTRIAL",
        status="READY",
        metrics={"revenue": 100.0},
        facts_used=[{"version": 1, "known_at": "2024-05-15"}],
    )
    restatement = FundamentalSnapshotV1(
        instrument_id=10,
        as_of=date(2024, 9, 1),
        known_at=date(2024, 8, 20),
        period_end=date(2024, 3, 31),
        issuer_kind="INDUSTRIAL",
        status="READY",
        metrics={"revenue": 80.0},
        facts_used=[{"version": 2, "known_at": "2024-08-20", "supersedes": 1}],
    )
    visible = [
        snap
        for snap in (original, restatement)
        if known_at_allows(as_of_v1, snap.known_at)
    ]
    assert len(visible) == 1
    assert visible[0].metrics["revenue"] == 100.0
    assert not known_at_allows(as_of_v1, restatement.known_at)


def test_period_end_is_not_known_at() -> None:
    """Economic period_end must not authorize decision-time visibility."""
    period_end = date(2023, 12, 31)
    as_of = date(2024, 1, 15)
    # Attacker tries to use period_end as if it were known_at.
    assert known_at_allows(as_of, period_end)  # date comparison alone is true…
    # …but honest provenance refuses known_at derived only from period_end.
    fabricated = honest_known_at(source_published_at=None, observed_at=as_of)
    assert fabricated is None
    snap = FundamentalSnapshotV1(
        instrument_id=1,
        as_of=as_of,
        known_at=None,
        period_end=period_end,
        status="UNKNOWN",
        limitations=("period_end_is_not_known_at",),
    )
    assert snap.known_at is None
    assert not known_at_allows(as_of, snap.known_at)


def test_article_published_after_as_of_invisible() -> None:
    as_of = date(2026, 3, 1)
    future_pub = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
    observed = datetime(2026, 3, 2, 11, 0, tzinfo=UTC)
    known = honest_known_at(source_published_at=future_pub, observed_at=observed)
    doc = SourceDocumentV1(
        id="doc-future",
        provider="rss_test",
        source_type="RSS",
        canonical_url="https://example.com/a",
        title="leak attempt",
        published_at=future_pub,
        observed_at=observed,
        known_at=known,
        content_hash=content_hash("body"),
    )
    assert pit_visible_docs([doc], as_of=as_of) == []
    ref = EvidenceRef(
        source_type="RSS",
        provider="rss_test",
        known_at=known,
        published_at=future_pub,
        observed_at=observed,
    )
    assert pit_visible_evidence([ref], as_of=as_of) == []


def test_observed_at_missing_blocks_known_at() -> None:
    published = date(2020, 1, 1)
    assert honest_known_at(source_published_at=published, observed_at=None) is None
    as_of = date(2026, 1, 1)
    doc = SourceDocumentV1(
        id="no-obs",
        provider="rss_test",
        source_type="RSS",
        canonical_url=None,
        title="missing observed",
        published_at=published,
        observed_at=None,
        known_at=None,
        content_hash=content_hash("x"),
    )
    assert pit_visible_docs([doc], as_of=as_of) == []


def test_signal_with_future_evidence_must_abstain_or_filter() -> None:
    as_of = date(2026, 5, 1)
    future_ref = EvidenceRef(
        source_type="FNS",
        provider="fns",
        known_at=date(2026, 5, 10),
        note="restatement not yet known",
    )
    usable = pit_visible_evidence([future_ref], as_of=as_of)
    assert usable == []
    # Without usable evidence the model contract path is ABSTAIN, not fabricated POSITIVE.
    sig = abstain_signal(
        model_id="FundamentalModelV1",
        model_version="1",
        semantic="FUNDAMENTAL",
        instrument_id=7,
        as_of=as_of,
        reason="no_pit_visible_evidence",
    )
    assert sig.state == "ABSTAIN"
    assert sig.score is None


def test_provenance_timestamps_keep_fields_distinct() -> None:
    stamps = ProvenanceTimestamps(
        source_published_at=date(2024, 1, 1),
        observed_at=date(2024, 2, 1),
        known_at=date(2024, 2, 1),
        effective_at=date(2023, 12, 31),
        period_end=date(2023, 12, 31),
        ingested_at=datetime(2024, 2, 1, 12, 0, tzinfo=UTC),
    )
    payload = stamps.to_dict()
    assert payload["period_end"] != payload["known_at"] or stamps.period_end != stamps.known_at
    assert payload["source_published_at"] != payload["observed_at"]
    assert payload["effective_at"] == "2023-12-31"


def test_look_ahead_signal_construction_rejects_broker_payload() -> None:
    with pytest.raises(ValueError, match="forbids keys"):
        SignalOutputV1(
            model_id="TechnicalModelV1",
            model_version="1",
            semantic="TECHNICAL",
            instrument_id=1,
            as_of=date(2026, 1, 1),
            known_at=date(2026, 1, 1),
            horizon="20d",
            state="POSITIVE",
            score=0.9,
            model_metadata={"broker": {"url": "http://evil"}},
        )
