"""Metric registry seeding. Mirrors METRIC_REGISTRY_SEED into fundamentals.metric_registry."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fundamentals.domain.types import METRIC_REGISTRY_SEED, MetricDefinition
from app.modules.fundamentals.infrastructure.models import MetricRegistryEntry


def ensure_metric_registry(session: Session) -> dict[str, int]:
    """Idempotent upsert. Titles/status follow the domain seed; unknown extra rows stay."""
    inserted = 0
    updated = 0
    existing = {row.code: row for row in session.scalars(select(MetricRegistryEntry))}
    for definition in METRIC_REGISTRY_SEED:
        row = existing.get(definition.code)
        if row is None:
            session.add(_to_row(definition))
            inserted += 1
            continue
        if _apply(row, definition):
            updated += 1
    session.flush()
    return {"inserted": inserted, "updated": updated, "total": len(METRIC_REGISTRY_SEED)}


def _to_row(definition: MetricDefinition) -> MetricRegistryEntry:
    return MetricRegistryEntry(
        code=definition.code,
        title_ru=definition.title_ru,
        title_en=definition.title_en,
        description=definition.description,
        applies_to_banks=definition.applies_to_banks,
        status=definition.status.value,
    )


def _apply(row: MetricRegistryEntry, definition: MetricDefinition) -> bool:
    changed = False
    for attr, value in (
        ("title_ru", definition.title_ru),
        ("title_en", definition.title_en),
        ("description", definition.description),
        ("applies_to_banks", definition.applies_to_banks),
        ("status", definition.status.value),
    ):
        if getattr(row, attr) != value:
            setattr(row, attr, value)
            changed = True
    return changed
