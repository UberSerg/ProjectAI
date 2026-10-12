"""PIT event feed into EventModel, without a second NEWS vote."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.intelligence.committee.decide import decide
from app.modules.intelligence.committee.policy_v1 import (
    HIGH_DISAGREEMENT,
    LIMITATION_NEWS_ZEROED_WHEN_EVENT,
)
from app.modules.intelligence.contracts.signal import SignalOutputV1
from app.modules.intelligence.extraction.refresh import refresh_extract_events
from app.modules.intelligence.news.models import IntelligenceEvent, IntelligenceSourceDocument
from app.modules.intelligence.resolution.decide import ResolutionCandidate
from app.modules.intelligence.signals.collect import (
    _load_instrument_events,
    collect_instrument_signals,
)

AS_OF = date(2026, 6, 1)
CUTOFF = datetime(2026, 6, 1, 23, 59, 59, 999999, tzinfo=UTC)
REFRESH_AS_OF = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_DIRECTIONAL = frozenset({"POSITIVE", "NEGATIVE", "NEUTRAL"})


@pytest.fixture
def quiet_other_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the feed tests on events and news coverage."""
    import app.modules.intelligence.signals.collect as collect_mod

    monkeypatch.setattr(collect_mod, "_load_technical_features", lambda *_a, **_k: None)
    monkeypatch.setattr(collect_mod, "_fundamental_payload", lambda *_a, **_k: None)
    monkeypatch.setattr(collect_mod, "_intraday_payload", lambda *_a, **_k: None)
    monkeypatch.setattr(collect_mod, "_macro_payload", lambda *_a, **_k: None)


def test_missing_session_does_not_invent_an_event_payload() -> None:
    assert collect_instrument_signals(instrument_id=1, as_of=AS_OF, session=None) is None


def test_future_known_at_is_excluded_from_event_model_input(
    core_db: Session,
    quiet_other_models: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instrument = _instrument(core_db)
    past_doc = _document(
        core_db,
        instrument_id=instrument.id,
        known_at=datetime(2026, 6, 1, 22, 0, tzinfo=UTC),
    )
    future_doc = _document(
        core_db,
        instrument_id=instrument.id,
        known_at=datetime(2026, 6, 2, 0, 0, 1, tzinfo=UTC),
    )
    _event(
        core_db,
        instrument_id=instrument.id,
        document_id=past_doc.id,
        known_at=datetime(2026, 6, 1, 23, 59, tzinfo=UTC),
        direction="NEGATIVE",
        materiality="HIGH",
        weight=1.0,
    )
    _event(
        core_db,
        instrument_id=instrument.id,
        document_id=future_doc.id,
        known_at=datetime(2026, 6, 2, 0, 0, 1, tzinfo=UTC),
        direction="POSITIVE",
        materiality="HIGH",
        weight=1.0,
    )

    import app.modules.intelligence.signals.collect as collect_mod

    captured: dict[str, object] = {}

    class _Spy(collect_mod.EventModelV1):
        def evaluate(self, *, instrument_id: int, as_of: date, events: object) -> SignalOutputV1:
            captured["events"] = events
            return super().evaluate(instrument_id=instrument_id, as_of=as_of, events=events)  # type: ignore[arg-type]

    monkeypatch.setattr(collect_mod, "EventModelV1", _Spy)
    signals = _collect(core_db, instrument.id)
    payloads = captured["events"]
    assert isinstance(payloads, list)
    assert payloads != []
    assert all(item["known_at"] <= CUTOFF for item in payloads)
    assert {item["source_document_id"] for item in payloads} == {past_doc.id}
    assert "future_known_at_excluded" not in _by_semantic(signals)["EVENT"].limitations
    assert _by_semantic(signals)["EVENT"].model_metadata["events_skipped_pit"] == 0


def test_negative_high_event_with_trusted_known_at_is_negative(
    core_db: Session, quiet_other_models: None
) -> None:
    instrument = _instrument(core_db)
    document = _document(
        core_db,
        instrument_id=instrument.id,
        known_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
    )
    _event(
        core_db,
        instrument_id=instrument.id,
        document_id=document.id,
        known_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
        direction="NEGATIVE",
        materiality="HIGH",
        weight=1.0,
        confidence=0.9,
    )
    payloads = _load_instrument_events(core_db, instrument.id, AS_OF)
    assert len(payloads) == 1
    assert payloads[0]["direction"] == "NEGATIVE"
    assert payloads[0]["materiality"] == pytest.approx(1.0)
    assert payloads[0]["timestamp_trusted"] is True
    assert payloads[0]["source_document_id"] == document.id
    assert payloads[0]["known_at"] is not None

    event = _by_semantic(_collect(core_db, instrument.id))["EVENT"]
    assert event.state == "NEGATIVE"
    assert event.score is not None and event.score < 0
    assert event.abstain_reason is None


def test_no_events_abstain_instead_of_neutral(core_db: Session, quiet_other_models: None) -> None:
    instrument = _instrument(core_db)
    event = _by_semantic(_collect(core_db, instrument.id))["EVENT"]
    assert event.state == "ABSTAIN"
    assert event.state != "NEUTRAL"
    assert event.abstain_reason == "no_valid_events"
    assert event.score is None


def test_unknown_direction_is_not_rewritten_as_neutral(
    core_db: Session, quiet_other_models: None
) -> None:
    instrument = _instrument(core_db)
    document = _document(
        core_db,
        instrument_id=instrument.id,
        known_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    )
    _event(
        core_db,
        instrument_id=instrument.id,
        document_id=document.id,
        known_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
        direction="UNKNOWN",
        materiality="HIGH",
        weight=1.0,
    )
    payloads = _load_instrument_events(core_db, instrument.id, AS_OF)
    assert payloads[0]["direction"] == "UNKNOWN"
    assert payloads[0]["direction"] != "NEUTRAL"
    event = _by_semantic(_collect(core_db, instrument.id))["EVENT"]
    assert event.state == "ABSTAIN"
    assert event.state != "NEUTRAL"
    assert event.score is None


def test_same_source_does_not_cast_news_and_event_votes(
    core_db: Session, quiet_other_models: None
) -> None:
    instrument = _instrument(core_db)
    known_at = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    document = _document(core_db, instrument_id=instrument.id, known_at=known_at)
    future = _document(
        core_db,
        instrument_id=instrument.id,
        known_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
    )
    _event(
        core_db,
        instrument_id=instrument.id,
        document_id=document.id,
        known_at=known_at,
        direction="NEGATIVE",
        materiality="HIGH",
        weight=1.0,
        confidence=0.9,
    )
    signals = _collect(core_db, instrument.id)
    by_semantic = _by_semantic(signals)
    event = by_semantic["EVENT"]
    news = by_semantic["NEWS"]

    assert event.state == "NEGATIVE"
    assert event.evidence_refs[0].source_document_id == str(document.id)
    assert news.state == "UNKNOWN"
    assert news.state not in _DIRECTIONAL
    assert news.score is None
    assert news.model_metadata["directional_vote"] is False
    assert "source_documents_in_coverage" in news.limitations
    assert {ref.source_document_id for ref in news.evidence_refs} == {str(document.id)}
    assert str(future.id) not in {ref.source_document_id for ref in news.evidence_refs}

    decision = decide(as_of=AS_OF, instrument_id=instrument.id, signals=signals)
    votes = {vote.model_id: vote for vote in decision.independent_model_votes}
    assert votes["EventModelV1"].weight_applied is not None
    assert votes["EventModelV1"].weight_applied > 0
    assert votes["EventModelV1"].state == "NEGATIVE"
    assert votes["NewsModelV1"].weight_applied == 0.0
    assert votes["NewsModelV1"].state not in _DIRECTIONAL
    assert LIMITATION_NEWS_ZEROED_WHEN_EVENT in decision.limitations
    voting = [
        vote.model_id
        for vote in decision.independent_model_votes
        if vote.model_id in {"NewsModelV1", "EventModelV1"}
        and (vote.weight_applied or 0) > 0
        and vote.state in _DIRECTIONAL
    ]
    assert voting == ["EventModelV1"]


def test_committee_preserves_disagreement_with_one_material_negative_event() -> None:
    technical = _sig("TechnicalModelV1", "TECHNICAL", "POSITIVE", 0.9, 0.8)
    fundamental = _sig("FundamentalModelV1", "FUNDAMENTAL", "NEGATIVE", -0.85, 0.8)
    event = _sig("EventModelV1", "EVENT", "NEGATIVE", -0.8, 0.85)
    news = _sig("NewsModelV1", "NEWS", "NEGATIVE", -0.8, 0.85)

    with_news = decide(
        as_of=AS_OF,
        instrument_id=42,
        signals=(technical, fundamental, event, news),
    )
    without_news = decide(
        as_of=AS_OF,
        instrument_id=42,
        signals=(technical, fundamental, event),
    )
    news_vote = next(vote for vote in with_news.independent_model_votes if vote.model_id == "NewsModelV1")
    assert news_vote.weight_applied == 0.0
    assert with_news.disagreement_score is not None
    assert with_news.disagreement_score == without_news.disagreement_score
    assert with_news.disagreement_score >= HIGH_DISAGREEMENT
    assert with_news.metadata["valid_model_count"] == 3
    assert with_news.advisory_state == "HOLD"
    weighted_states = {
        vote.state
        for vote in with_news.independent_model_votes
        if (vote.weight_applied or 0) > 0
    }
    assert weighted_states == {"POSITIVE", "NEGATIVE"}
    assert all(not item.startswith("NewsModelV1") for item in with_news.primary_drivers)
    assert all(not item.startswith("NewsModelV1") for item in with_news.counterarguments)

    news_still_votes = decide(as_of=AS_OF, instrument_id=42, signals=(technical, news))
    uncovered = next(
        vote for vote in news_still_votes.independent_model_votes if vote.model_id == "NewsModelV1"
    )
    assert uncovered.weight_applied is not None and uncovered.weight_applied > 0


def test_refresh_resolves_unmapped_documents_without_rewriting_known_at(
    core_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    instrument = _instrument(core_db)
    symbol = instrument.symbol
    mapped_known = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    ambiguous_known = datetime(2026, 5, 21, 10, 0, tzinfo=UTC)
    plain_known = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)
    late_same_day = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
    future_known = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)
    mapped = _document(
        core_db,
        instrument_id=None,
        known_at=mapped_known,
        text=f"The board increased the dividend to 8 RUB per share for 2024. {symbol}",
    )
    ambiguous = _document(
        core_db,
        instrument_id=None,
        known_at=ambiguous_known,
        text=f"Commentary mentions {symbol} and ZZZZTEST only.",
    )
    plain = _document(
        core_db,
        instrument_id=None,
        known_at=plain_known,
        text="Nothing identifiable is written here.",
    )
    late = _document(
        core_db,
        instrument_id=None,
        known_at=late_same_day,
        text=f"The board increased the dividend to 9 RUB per share for 2024. {symbol}",
    )
    future = _document(
        core_db,
        instrument_id=None,
        known_at=future_known,
        text=f"The board increased the dividend to 10 RUB per share for 2024. {symbol}",
    )
    seen_dates: list[date] = []

    def _candidates(_session: Session, as_of: date) -> list[ResolutionCandidate]:
        seen_dates.append(as_of)
        return [
            ResolutionCandidate(instrument_id=instrument.id, issuer_id=1, symbol=symbol),
            ResolutionCandidate(instrument_id=instrument.id + 1_000_000, issuer_id=2, symbol="ZZZZTEST"),
        ]

    monkeypatch.setattr(
        "app.modules.intelligence.resolution.session.load_resolution_candidates",
        _candidates,
    )
    result = refresh_extract_events(
        core_db,
        {
            "dry_run": False,
            "live_fetch": True,
            "as_of": REFRESH_AS_OF,
            "document_ids": [mapped.id, ambiguous.id, plain.id, late.id, future.id],
        },
    )
    assert result["reason"] == "DETERMINISTIC_PASS_LLM_UNAVAILABLE"
    assert result["llm"]["provider_invoked"] is False
    assert result["llm"]["events_fabricated"] is False

    assert mapped.instrument_id == instrument.id
    assert mapped.known_at == mapped_known
    assert mapped.published_at is not None
    assert _event_count(core_db, mapped.id) == 1

    assert ambiguous.instrument_id is None
    assert ambiguous.mapping_basis == "SECID"
    assert ambiguous.known_at == ambiguous_known
    assert ambiguous.metadata_["company_resolution"]["status"] == "AMBIGUOUS"
    assert _event_count(core_db, ambiguous.id) == 0

    assert plain.instrument_id is None
    assert plain.mapping_basis == "UNMAPPED"
    assert plain.known_at == plain_known

    assert late.instrument_id is None
    assert "company_resolution" not in (late.metadata_ or {})
    assert late.known_at == late_same_day
    assert _event_count(core_db, late.id) == 0

    assert future.instrument_id is None
    assert "company_resolution" not in (future.metadata_ or {})
    assert future.known_at == future_known
    assert set(seen_dates).isdisjoint({late_same_day.date(), future_known.date()})


def _collect(session: Session, instrument_id: int) -> tuple[SignalOutputV1, ...]:
    signals = collect_instrument_signals(instrument_id=instrument_id, as_of=AS_OF, session=session)
    assert signals is not None
    return signals


def _by_semantic(signals: tuple[SignalOutputV1, ...]) -> dict[str, SignalOutputV1]:
    return {signal.semantic: signal for signal in signals}


def _sig(
    model_id: str,
    semantic: str,
    state: str,
    score: float,
    confidence: float,
) -> SignalOutputV1:
    return SignalOutputV1(
        model_id=model_id,
        model_version="1",
        semantic=semantic,
        instrument_id=42,
        as_of=AS_OF,
        known_at=AS_OF,
        horizon="event_window",
        state=state,  # type: ignore[arg-type]
        score=score,
        confidence=confidence,
    )


def _instrument(session: Session) -> Instrument:
    row = Instrument(
        symbol=f"IAE{uuid4().hex[:8].upper()}",
        name="IA E events",
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
    instrument_id: int | None,
    known_at: datetime,
    text: str = "Stored source document.",
) -> IntelligenceSourceDocument:
    published = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
    observed = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
    row = IntelligenceSourceDocument(
        document_key=f"ia-e-{uuid4().hex}",
        provider="ia-e-test",
        source_type="UNIT_TEST",
        title="unit",
        published_at=published,
        observed_at=observed,
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


def _event(
    session: Session,
    *,
    instrument_id: int,
    document_id: int,
    known_at: datetime,
    direction: str,
    materiality: str,
    weight: float | None,
    confidence: float = 0.8,
) -> IntelligenceEvent:
    row = IntelligenceEvent(
        instrument_id=instrument_id,
        event_type="EARNINGS_RESULTS",
        materiality=materiality,
        direction=direction,
        title="stored event",
        known_at=known_at,
        published_at=known_at,
        observed_at=known_at,
        source_document_id=document_id,
        payload={
            "materiality_weight": weight,
            "confidence": confidence,
        },
    )
    session.add(row)
    session.flush()
    return row


def _event_count(session: Session, document_id: int) -> int:
    from sqlalchemy import select

    rows = session.scalars(
        select(IntelligenceEvent).where(IntelligenceEvent.source_document_id == document_id)
    ).all()
    return len(rows)
