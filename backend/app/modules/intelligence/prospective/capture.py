"""Append-only record of what a live refresh could actually see.

A new refresh inserts another row. It does not update an older capture.
This is not accuracy and has no win rate.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
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
    from app.modules.intelligence.application.snapshot_builder import build_intelligence_snapshot

    captured_at = datetime.now(UTC)
    instrument = session.get(Instrument, instrument_id)
    snapshot = build_intelligence_snapshot(
        instrument=instrument,
        instrument_id=instrument_id,
        as_of=as_of,
        generated_at=captured_at,
        session=session,
    )
    payload = _payload_from_snapshot(snapshot.to_dict(), captured_at)
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


def _payload_from_snapshot(body: dict[str, Any], captured_at: datetime) -> dict[str, Any]:
    """Copy the canonical snapshot. Do not recompute committee, risk, or knowledge."""
    signals = list(body.get("signals") or [])
    committee = dict(body.get("committee") or {})
    evidence: list[Any] = []
    for signal in signals:
        evidence.extend(signal.get("evidence_refs") or [])
    evidence.extend(committee.get("evidence_refs") or [])
    event_model = next(
        (item for item in signals if item.get("model_id") == "EventModelV1"),
        None,
    )
    return {
        "schema": "ProspectiveCaptureV1",
        "coverage_not_accuracy": True,
        "captured_at": captured_at.isoformat(),
        "instrument_id": body.get("instrument_id"),
        "symbol": body.get("symbol"),
        "as_of": body.get("as_of"),
        "signals": signals,
        "event_model": event_model,
        "committee": committee,
        "risk": body.get("risk"),
        "knowledge_evaluations": list(body.get("knowledge_evaluations") or []),
        "fundamentals_summary": dict(body.get("fundamentals_summary") or {}),
        "recent_events": list(body.get("recent_events") or []),
        "macro_summary": dict(body.get("macro_summary") or {}),
        "intraday_summary": dict(body.get("intraday_summary") or {}),
        "production_isolation": dict(body.get("production_isolation") or {}),
        "disagreement": committee.get("disagreement_score"),
        "drivers": list(committee.get("primary_drivers") or []),
        "counterarguments": list(committee.get("counterarguments") or []),
        "gaps": list(committee.get("data_gaps") or []),
        "policy_version": committee.get("committee_policy_version"),
        "model_versions": {
            str(item.get("model_id")): item.get("model_version") for item in signals
        },
        "evidence_refs": evidence,
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
