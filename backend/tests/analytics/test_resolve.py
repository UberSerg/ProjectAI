"""Feature set resolve semantics — active vs explicit version."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import FeatureSet
from app.modules.analytics.application.resolve import FeatureSetResolveError, resolve_feature_set
from app.modules.analytics.application.seed import seed_feature_sets


def _ensure_v2(session: Session) -> FeatureSet:
    existing = session.scalar(
        select(FeatureSet).where(FeatureSet.code == "basic_daily", FeatureSet.version == 2)
    )
    if existing:
        return existing
    row = FeatureSet(
        code="basic_daily",
        version=2,
        description="basic_daily v2 test",
        parameters={"return_windows": [1]},
        is_active=False,
        updated_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def _activate_version(session: Session, code: str, version: int) -> FeatureSet:
    """Flip active version without violating one-active-per-code unique index."""
    session.execute(update(FeatureSet).where(FeatureSet.code == code).values(is_active=False))
    session.flush()
    row = session.scalar(select(FeatureSet).where(FeatureSet.code == code, FeatureSet.version == version))
    assert row is not None
    row.is_active = True
    session.flush()
    return row


def test_resolve_without_version_uses_active_v1(core_db: Session) -> None:
    seed_feature_sets(core_db)
    fs = resolve_feature_set(core_db, "basic_daily")
    assert fs.version == 1
    assert fs.is_active is True


def test_resolve_without_version_uses_active_v2(core_db: Session) -> None:
    seed_feature_sets(core_db)
    _ensure_v2(core_db)
    v2 = _activate_version(core_db, "basic_daily", 2)
    fs = resolve_feature_set(core_db, "basic_daily")
    assert fs.id == v2.id
    assert fs.version == 2


def test_resolve_explicit_version_gets_v1_even_if_inactive(core_db: Session) -> None:
    seed_feature_sets(core_db)
    _ensure_v2(core_db)
    _activate_version(core_db, "basic_daily", 2)
    fs = resolve_feature_set(core_db, "basic_daily", version=1)
    assert fs.version == 1
    assert fs.is_active is False


def test_resolve_nonexistent_version_raises_404(core_db: Session) -> None:
    seed_feature_sets(core_db)
    with pytest.raises(FeatureSetResolveError) as exc:
        resolve_feature_set(core_db, "basic_daily", version=99)
    assert exc.value.status_code == 404


def test_resolve_no_active_does_not_pick_arbitrary_first(core_db: Session) -> None:
    seed_feature_sets(core_db)
    _ensure_v2(core_db)
    core_db.execute(update(FeatureSet).where(FeatureSet.code == "basic_daily").values(is_active=False))
    core_db.flush()
    with pytest.raises(FeatureSetResolveError) as exc:
        resolve_feature_set(core_db, "basic_daily")
    assert exc.value.status_code == 404
    assert "No active" in exc.value.message


def test_resolve_multiple_active_raises_409() -> None:
    session = MagicMock()
    session.scalars.return_value.all.return_value = [
        FeatureSet(code="basic_daily", version=1, parameters={}, is_active=True),
        FeatureSet(code="basic_daily", version=2, parameters={}, is_active=True),
    ]
    with pytest.raises(FeatureSetResolveError) as exc:
        resolve_feature_set(session, "basic_daily")
    assert exc.value.status_code == 409
