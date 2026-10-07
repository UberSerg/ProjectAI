"""Persist IntradayFeatureSnapshotV1 into intelligence.intraday_feature_snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.snapshots_domain import IntradayFeatureSnapshotV1


def feature_hash(features: dict[str, float | None]) -> str:
    payload = json.dumps(features, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _known_at_ts(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime.min.time())


def upsert_feature_snapshot(session: Session, snap: IntradayFeatureSnapshotV1) -> dict[str, Any]:
    """Idempotent upsert on (instrument_id, as_of, interval)."""
    fhash = feature_hash(snap.features)
    known_at = _known_at_ts(snap.known_at)
    if known_at is None:
        raise ValueError("known_at is required for intraday feature snapshot")
    session.execute(
        text(
            """
            INSERT INTO intelligence.intraday_feature_snapshots (
                instrument_id, as_of, known_at, interval, coverage_status,
                features, bars_used, feature_hash, limitations
            ) VALUES (
                :instrument_id, :as_of, :known_at, :interval, :coverage_status,
                CAST(:features AS jsonb), :bars_used, :feature_hash, CAST(:limitations AS jsonb)
            )
            ON CONFLICT (instrument_id, as_of, interval) DO UPDATE SET
                known_at = EXCLUDED.known_at,
                coverage_status = EXCLUDED.coverage_status,
                features = EXCLUDED.features,
                bars_used = EXCLUDED.bars_used,
                feature_hash = EXCLUDED.feature_hash,
                limitations = EXCLUDED.limitations
            """
        ),
        {
            "instrument_id": snap.instrument_id,
            "as_of": snap.as_of,
            "known_at": known_at,
            "interval": snap.interval,
            "coverage_status": snap.coverage_status,
            "features": json.dumps(snap.features, default=str),
            "bars_used": snap.bars_used,
            "feature_hash": fhash,
            "limitations": json.dumps(list(snap.limitations)),
        },
    )
    return {
        "instrument_id": snap.instrument_id,
        "as_of": snap.as_of.isoformat() if snap.as_of else None,
        "interval": snap.interval,
        "coverage_status": snap.coverage_status,
        "bars_used": snap.bars_used,
        "feature_hash": fhash,
    }


def table_available(session: Session) -> bool:
    return bool(
        session.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'intelligence'
                      AND table_name = 'intraday_feature_snapshots'
                )
                """
            )
        )
    )
