"""Resolve relation set by code and optional version."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.analytics.relation_models import RelationSet


class RelationSetResolveError(Exception):
    def __init__(self, message: str, *, status_code: int = 404) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def resolve_relation_set(
    session: Session,
    code: str,
    version: int | None = None,
) -> RelationSet:
    if version is not None:
        row = session.scalar(
            select(RelationSet).where(RelationSet.code == code, RelationSet.version == version)
        )
        if row is None:
            raise RelationSetResolveError(
                f"Relation set not found: code={code!r} version={version}",
                status_code=404,
            )
        return row

    active = list(
        session.scalars(
            select(RelationSet)
            .where(RelationSet.code == code, RelationSet.is_active.is_(True))
            .order_by(RelationSet.version)
        ).all()
    )
    if len(active) == 1:
        return active[0]
    if not active:
        raise RelationSetResolveError(f"No active relation set for code={code!r}", status_code=404)
    raise RelationSetResolveError(
        f"Multiple active relation sets for code={code!r}; pass relation_set_version",
        status_code=409,
    )
