"""Optional persistence into intelligence.macro_snapshots (orchestrator migration)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.snapshots_domain import MacroSnapshotV1


def schema_ready(session: Session) -> bool:
    row = session.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'intelligence'
                  AND table_name = 'macro_snapshots'
            )
            """
        )
    ).scalar()
    return bool(row)


def _known_at_ts(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _snapshot_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def persist_macro_snapshot(
    session: Session,
    snapshot: MacroSnapshotV1,
    *,
    commit: bool = False,
) -> dict[str, Any]:
    """Upsert snapshot when the intelligence table exists. No-op otherwise."""
    if not schema_ready(session):
        return {
            "persisted": False,
            "reason": "intelligence.macro_snapshots missing "
            "(apply alembic 20261007_0027)",
        }

    payload = snapshot.to_dict()
    known_at = _known_at_ts(snapshot.known_at)
    if known_at is None:
        return {"persisted": False, "reason": "known_at required for persistence"}
    if snapshot.as_of is None:
        return {"persisted": False, "reason": "as_of required for persistence"}

    snap_hash = _snapshot_hash(payload)
    session.execute(
        text(
            """
            INSERT INTO intelligence.macro_snapshots (
                as_of, known_at, status, observations, regimes,
                sources, limitations, snapshot_hash
            ) VALUES (
                :as_of, :known_at, :status,
                CAST(:observations AS jsonb), CAST(:regimes AS jsonb),
                CAST(:sources AS jsonb), CAST(:limitations AS jsonb),
                :snapshot_hash
            )
            ON CONFLICT (as_of) DO UPDATE SET
                known_at = EXCLUDED.known_at,
                status = EXCLUDED.status,
                observations = EXCLUDED.observations,
                regimes = EXCLUDED.regimes,
                sources = EXCLUDED.sources,
                limitations = EXCLUDED.limitations,
                snapshot_hash = EXCLUDED.snapshot_hash
            """
        ),
        {
            "as_of": snapshot.as_of,
            "known_at": known_at,
            "status": snapshot.status,
            "observations": json.dumps(payload.get("observations") or {}, default=str),
            "regimes": json.dumps(payload.get("regimes") or {}, default=str),
            "sources": json.dumps(payload.get("sources") or [], default=str),
            "limitations": json.dumps(payload.get("limitations") or [], default=str),
            "snapshot_hash": snap_hash,
        },
    )
    if commit:
        session.commit()
    else:
        session.flush()
    return {"persisted": True, "snapshot_hash": snap_hash}
