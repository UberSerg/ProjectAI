"""Optional persistence into intelligence.fundamental_snapshots (orchestrator migration)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.snapshots_domain import FundamentalSnapshotV1


def schema_ready(session: Session) -> bool:
    row = session.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'intelligence'
                  AND table_name = 'fundamental_snapshots'
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


def persist_fundamental_snapshot(
    session: Session,
    snapshot: FundamentalSnapshotV1,
    *,
    commit: bool = False,
) -> dict[str, Any]:
    """Upsert snapshot when the intelligence table exists. No-op otherwise."""
    if not schema_ready(session):
        return {
            "persisted": False,
            "reason": "intelligence.fundamental_snapshots missing "
            "(apply alembic 20261007_0027)",
        }

    payload = snapshot.to_dict()
    known_at = _known_at_ts(snapshot.known_at)
    if known_at is None:
        return {"persisted": False, "reason": "known_at required for persistence"}

    snap_hash = _snapshot_hash(payload)
    session.execute(
        text(
            """
            INSERT INTO intelligence.fundamental_snapshots (
                instrument_id, as_of, known_at, period_end, issuer_kind, status,
                metrics, missing_metrics, facts_used, limitations, provider, snapshot_hash
            ) VALUES (
                :instrument_id, :as_of, :known_at, :period_end, :issuer_kind, :status,
                CAST(:metrics AS jsonb), CAST(:missing_metrics AS jsonb),
                CAST(:facts_used AS jsonb), CAST(:limitations AS jsonb),
                :provider, :snapshot_hash
            )
            ON CONFLICT (instrument_id, as_of, issuer_kind) DO UPDATE SET
                known_at = EXCLUDED.known_at,
                period_end = EXCLUDED.period_end,
                status = EXCLUDED.status,
                metrics = EXCLUDED.metrics,
                missing_metrics = EXCLUDED.missing_metrics,
                facts_used = EXCLUDED.facts_used,
                limitations = EXCLUDED.limitations,
                provider = EXCLUDED.provider,
                snapshot_hash = EXCLUDED.snapshot_hash
            """
        ),
        {
            "instrument_id": int(snapshot.instrument_id),
            "as_of": snapshot.as_of,
            "known_at": known_at,
            "period_end": snapshot.period_end,
            "issuer_kind": snapshot.issuer_kind,
            "status": snapshot.status,
            "metrics": json.dumps(payload.get("metrics") or {}, default=str),
            "missing_metrics": json.dumps(payload.get("missing_metrics") or [], default=str),
            "facts_used": json.dumps(payload.get("facts_used") or [], default=str),
            "limitations": json.dumps(payload.get("limitations") or [], default=str),
            "provider": snapshot.provider,
            "snapshot_hash": snap_hash,
        },
    )
    if commit:
        session.commit()
    else:
        session.flush()
    return {"persisted": True, "snapshot_hash": snap_hash}
