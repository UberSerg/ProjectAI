"""EventModelV1 — structured events → SignalOutputV1.

Weights recency, materiality, confidence; preserves conflict. Not a sentiment oracle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from app.modules.intelligence.contracts.provenance import EvidenceRef
from app.modules.intelligence.contracts.signal import SignalOutputV1, abstain_signal, unknown_signal
from app.modules.intelligence.signals.base import (
    clip,
    optional_float,
    parse_as_of,
    parse_known_at,
    pit_allows,
    score_to_state,
)

MODEL_ID = "EventModelV1"
MODEL_VERSION = "1"
SEMANTIC = "EVENT"
HORIZON = "event_window"

_HALF_LIFE_DAYS = 14.0
_CONFLICT_GAP = 0.35  # simultaneous strong opposite poles ⇒ dampen


def _polarity_score(event: Mapping[str, Any]) -> float | None:
    if "score" in event and event.get("score") is not None:
        return optional_float(event.get("score"))
    polarity = event.get("polarity") or event.get("direction") or event.get("sentiment")
    if polarity is None:
        return None
    if isinstance(polarity, int | float):
        return optional_float(polarity)
    text = str(polarity).upper()
    mapping = {
        "POSITIVE": 1.0,
        "BULLISH": 1.0,
        "SUPPORTIVE": 0.7,
        "NEUTRAL": 0.0,
        "NEGATIVE": -1.0,
        "BEARISH": -1.0,
        "ADVERSE": -0.7,
        "UNKNOWN": None,
        "ABSTAIN": None,
    }
    if text not in mapping:
        return None
    return mapping[text]


def _recency_weight(as_of: date, known_at: date | datetime) -> float:
    known_d = known_at.date() if isinstance(known_at, datetime) else known_at
    age = max(0, (as_of - known_d).days)
    # Exponential decay; same-day ≈ 1.0
    return float(0.5 ** (age / _HALF_LIFE_DAYS))


def _event_weight(event: Mapping[str, Any], as_of: date, known_at: date | datetime) -> float:
    materiality = optional_float(event.get("materiality"))
    if materiality is None:
        materiality = 0.5
    materiality = clip(materiality, 0.0, 1.0)
    confidence = optional_float(event.get("confidence"))
    if confidence is None:
        confidence = 0.5
    confidence = clip(confidence, 0.0, 1.0)
    return _recency_weight(as_of, known_at) * materiality * confidence


class EventModelV1:
    model_id = MODEL_ID
    model_version = MODEL_VERSION
    semantic = SEMANTIC

    def evaluate(
        self,
        *,
        instrument_id: int,
        as_of: date | datetime | str,
        events: Sequence[Mapping[str, Any]] | None,
    ) -> SignalOutputV1:
        as_of_d = parse_as_of(as_of)
        if as_of_d is None:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=date.today(),
                reason="missing_as_of",
                horizon=HORIZON,
            )

        if events is None:
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="events_payload_missing",
                horizon=HORIZON,
            )

        if len(events) == 0:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="no_valid_events",
                horizon=HORIZON,
            )

        weighted: list[tuple[float, float, Mapping[str, Any]]] = []
        skipped_untrusted = 0
        skipped_pit = 0
        for event in events:
            known_at = parse_known_at(event.get("known_at"))
            if known_at is None:
                skipped_untrusted += 1
                continue
            if not pit_allows(as_of_d, known_at):
                skipped_pit += 1
                continue
            if event.get("timestamp_trusted") is False:
                skipped_untrusted += 1
                continue
            score = _polarity_score(event)
            if score is None:
                skipped_untrusted += 1
                continue
            score = clip(score)
            w = _event_weight(event, as_of_d, known_at)
            if w <= 0:
                continue
            weighted.append((w, score, event))

        if not weighted:
            reason = "no_pit_valid_events"
            if skipped_untrusted and not skipped_pit:
                reason = "events_untrusted_or_unscored"
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason=reason,
                horizon=HORIZON,
                limitations=("event_timestamp_untrusted",) if skipped_untrusted else (),
            )

        w_sum = sum(w for w, _, _ in weighted)
        raw_score = sum(w * s for w, s, _ in weighted) / w_sum

        pos_mass = sum(w for w, s, _ in weighted if s > 0)
        neg_mass = sum(w for w, s, _ in weighted if s < 0)
        conflict = 0.0
        if pos_mass > 0 and neg_mass > 0:
            conflict = min(pos_mass, neg_mass) / max(pos_mass + neg_mass, 1e-9)
            if conflict >= _CONFLICT_GAP:
                raw_score *= 1.0 - conflict

        score = clip(raw_score)
        avg_conf = sum(
            (optional_float(e.get("confidence")) or 0.5) * w for w, _, e in weighted
        ) / w_sum
        confidence = clip((1.0 - conflict) * avg_conf * min(1.0, w_sum), 0.0, 1.0)

        refs = tuple(
            EvidenceRef(
                source_type="structured_event",
                provider=str(e.get("provider") or "events"),
                source_document_id=str(e["event_id"]) if e.get("event_id") is not None else None,
                known_at=parse_known_at(e.get("known_at")),
                content_hash=str(e["content_hash"]) if e.get("content_hash") else None,
                note=str(e.get("event_type") or "event"),
            )
            for _, _, e in weighted[:10]
        )

        limitations: list[str] = []
        if conflict >= _CONFLICT_GAP:
            limitations.append("conflicting_events")
        if skipped_pit:
            limitations.append("future_known_at_excluded")
        if skipped_untrusted:
            limitations.append("untrusted_events_excluded")

        latest_known: date | datetime | None = None
        latest_key: date | None = None
        for _, _, event in weighted:
            ka = parse_known_at(event.get("known_at"))
            key = parse_as_of(ka)
            if key is None:
                continue
            if latest_key is None or key > latest_key:
                latest_key = key
                latest_known = ka

        return SignalOutputV1(
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            semantic=SEMANTIC,
            instrument_id=instrument_id,
            as_of=as_of_d,
            known_at=latest_known,
            horizon=HORIZON,
            state=score_to_state(score),
            score=score,
            confidence=confidence,
            confidence_semantic="AGREEMENT",
            evidence_refs=refs,
            limitations=tuple(limitations),
            model_metadata={
                "events_used": len(weighted),
                "events_skipped_pit": skipped_pit,
                "events_skipped_untrusted": skipped_untrusted,
                "conflict_score": conflict,
                "weight_sum": w_sum,
                "candidate_promotion": False,
            },
        )
