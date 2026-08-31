"""Resolve feature set by code and optional version (active when version omitted)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import FeatureSet


class FeatureSetResolveError(Exception):
    """Feature set could not be resolved unambiguously."""

    def __init__(self, message: str, *, status_code: int = 404) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def resolve_feature_set(
    session: Session,
    code: str,
    version: int | None = None,
) -> FeatureSet:
    """Resolve a feature set.

    - version given → exact (code, version); missing → 404
    - version omitted → the single active row for code
    - no active → 404
    - multiple active for same code → 409 (never arbitrary first())
    """
    if version is not None:
        row = session.scalar(
            select(FeatureSet).where(FeatureSet.code == code, FeatureSet.version == version)
        )
        if row is None:
            raise FeatureSetResolveError(
                f"Feature set not found: code={code!r} version={version}",
                status_code=404,
            )
        return row

    active = list(
        session.scalars(
            select(FeatureSet)
            .where(FeatureSet.code == code, FeatureSet.is_active.is_(True))
            .order_by(FeatureSet.version)
        ).all()
    )
    if len(active) == 1:
        return active[0]
    if not active:
        raise FeatureSetResolveError(
            f"No active feature set for code={code!r}",
            status_code=404,
        )
    raise FeatureSetResolveError(
        f"Multiple active feature sets for code={code!r}; pass feature_set_version",
        status_code=409,
    )
