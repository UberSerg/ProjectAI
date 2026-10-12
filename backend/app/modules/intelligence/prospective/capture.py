"""Append-only record of what a live refresh could actually see.

A new refresh inserts another row. It does not update an older capture.
This is not accuracy and has no win rate.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session


def capture_live_refresh(session: Session, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Insert one capture per requested instrument. Returns the new row identities."""
    as_of = _as_of(ctx.get("as_of"))
    written: list[dict[str, Any]] = []
    for raw_id in ctx.get("instrument_ids") or []:
        written.append(_insert_one(session, instrument_id=int(raw_id), as_of=as_of))
    if written:
        session.flush()
    return written


def read_prospective_capture(session: Session, capture_id: int) -> dict[str, Any] | None:
    """Read one capture back and confirm its stored hash."""
    row = session.execute(
        text(
            """
            SELECT id, captured_at, instrument_id, as_of, payload, payload_hash
            FROM intelligence.prospective_captures
            WHERE id = :id
            """
        ),
        {"id": int(capture_id)},
    ).mappings().first()
    if row is None:
        return None
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    digest = _hash_payload(payload)
    return {
        "id": int(row["id"]),
        "captured_at": row["captured_at"],
        "instrument_id": int(row["instrument_id"]),
        "as_of": row["as_of"],
        "payload": payload,
        "payload_hash": row["payload_hash"],
        "hash_matches": row["payload_hash"] == digest,
    }


def _insert_one(session: Session, *, instrument_id: int, as_of: date) -> dict[str, Any]:
    from app.infrastructure.market.models import Instrument
    from app.modules.intelligence.committee import decide_committee
    from app.modules.intelligence.news.models import IntelligenceEvent, IntelligenceSourceDocument
    from app.modules.intelligence.signals.collect import collect_instrument_signals

    captured_at = datetime.now(UTC)
    cutoff = datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59, 999999, tzinfo=UTC)
    instrument = session.get(Instrument, instrument_id)
    documents = list(
        session.scalars(
            select(IntelligenceSourceDocument)
            .where(
                IntelligenceSourceDocument.instrument_id == instrument_id,
                IntelligenceSourceDocument.known_at <= cutoff,
            )
            .order_by(IntelligenceSourceDocument.id.asc())
        ).all()
    )
    events = list(
        session.scalars(
            select(IntelligenceEvent)
            .where(
                IntelligenceEvent.instrument_id == instrument_id,
                IntelligenceEvent.known_at <= cutoff,
            )
            .order_by(IntelligenceEvent.id.asc())
        ).all()
    )
    signals = collect_instrument_signals(
        instrument_id=instrument_id,
        as_of=as_of,
        session=session,
    ) or ()
    decision = decide_committee(instrument_id=instrument_id, as_of=as_of, signals=signals)
    signal_payloads = [signal.to_dict() for signal in signals]
    event_model = next((item for item in signal_payloads if item.get("model_id") == "EventModelV1"), None)
    evidence = []
    for signal in signals:
        evidence.extend(ref.to_dict() for ref in signal.evidence_refs)
    evidence.extend(ref.to_dict() for ref in decision.evidence_refs)
    payload = {
        "schema": "ProspectiveCaptureV1",
        "coverage_not_accuracy": True,
        "captured_at": captured_at.isoformat(),
        "instrument_id": instrument_id,
        "symbol": None if instrument is None else instrument.symbol,
        "as_of": as_of.isoformat(),
        "source_documents": [_document_view(row) for row in documents],
        "events": [_event_view(row) for row in events],
        "signals": signal_payloads,
        "event_model": event_model,
        "committee": decision.to_dict(),
        "disagreement": decision.disagreement_score,
        "drivers": list(decision.primary_drivers),
        "counterarguments": list(decision.counterarguments),
        "gaps": list(decision.data_gaps),
        "policy_version": decision.committee_policy_version,
        "model_versions": {
            signal.model_id: signal.model_version for signal in signals
        },
        "evidence_refs": evidence,
    }
    digest = _hash_payload(payload)
    capture_id = session.execute(
        text(
            """
            INSERT INTO intelligence.prospective_captures (
                captured_at, instrument_id, as_of, payload, payload_hash
            ) VALUES (
                :captured_at, :instrument_id, :as_of, CAST(:payload AS jsonb), :payload_hash
            )
            RETURNING id
            """
        ),
        {
            "captured_at": captured_at,
            "instrument_id": instrument_id,
            "as_of": as_of,
            "payload": json.dumps(payload, ensure_ascii=False, default=str),
            "payload_hash": digest,
        },
    ).scalar_one()
    return {
        "id": int(capture_id),
        "instrument_id": instrument_id,
        "captured_at": captured_at.isoformat(),
        "payload_hash": digest,
    }


def _document_view(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "title": row.title,
        "known_at": row.known_at.isoformat() if row.known_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "mapping_basis": row.mapping_basis,
        "instrument_id": row.instrument_id,
    }


def _event_view(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "direction": row.direction,
        "materiality": row.materiality,
        "known_at": row.known_at.isoformat() if row.known_at else None,
        "source_document_id": row.source_document_id,
    }


def _as_of(raw: Any) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if raw:
        return date.fromisoformat(str(raw)[:10])
    return datetime.now(UTC).date()


def _hash_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
