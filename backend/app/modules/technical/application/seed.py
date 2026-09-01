"""Idempotent seed for technical_daily feature set."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import FeatureSet
from app.modules.analytics.feature_config import FEATURE_SETS
from app.modules.technical.technical_config import TECHNICAL_FEATURE_SETS


def seed_technical_feature_sets(session: Session) -> dict[str, int]:
    """Ensure technical_daily (+ analytics basic sets) exist; activate one version per code."""
    all_defs = tuple(FEATURE_SETS) + tuple(TECHNICAL_FEATURE_SETS)
    ensured = 0
    for definition in all_defs:
        stmt = insert(FeatureSet).values(
            code=definition["code"],
            version=definition["version"],
            description=definition["description"],
            parameters=definition["parameters"],
            is_active=False,
            updated_at=datetime.now(UTC),
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_analytics_feature_sets_code_version",
            set_={
                "description": stmt.excluded.description,
                "parameters": stmt.excluded.parameters,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        session.execute(stmt)
        ensured += 1

    # One active version per code (partial unique index allows different codes).
    session.execute(update(FeatureSet).values(is_active=False))
    activated = 0
    seen_codes: set[str] = set()
    for definition in all_defs:
        code = definition["code"]
        if code in seen_codes:
            continue
        seen_codes.add(code)
        row = session.scalar(
            select(FeatureSet).where(FeatureSet.code == code, FeatureSet.version == definition["version"])
        )
        if row is not None:
            row.is_active = True
            activated += 1
    session.flush()
    return {"ensured": ensured, "activated": activated}
