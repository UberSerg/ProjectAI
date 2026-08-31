"""Idempotent seed for analytics feature sets."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import FeatureSet
from app.modules.analytics.feature_config import FEATURE_SETS


def seed_feature_sets(session: Session) -> dict[str, int]:
    """Ensure configured feature sets exist; activate basic_daily v1."""
    ensured = 0
    for definition in FEATURE_SETS:
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

    session.execute(update(FeatureSet).values(is_active=False))
    basic = session.scalar(
        select(FeatureSet).where(FeatureSet.code == "basic_daily", FeatureSet.version == 1)
    )
    activated = 0
    if basic:
        basic.is_active = True
        activated = 1
    session.flush()
    return {"ensured": ensured, "activated": activated}
