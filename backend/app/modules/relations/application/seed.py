"""Idempotent seed for relation sets and default relation inputs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.analytics.relation_models import RelationInput, RelationSet
from app.infrastructure.market.models import Instrument, Series
from app.modules.relations.relation_config import (
    INSTRUMENT_ALIGNMENT,
    INSTRUMENT_FEATURE_KEY,
    INSTRUMENT_TRANSFORM,
    RELATION_SETS,
    SERIES_INPUT_TRANSFORMS,
)


def seed_relation_sets(session: Session) -> dict[str, int]:
    ensured = 0
    for definition in RELATION_SETS:
        stmt = insert(RelationSet).values(
            code=definition["code"],
            version=definition["version"],
            description=definition["description"],
            parameters=definition["parameters"],
            is_active=False,
            updated_at=datetime.now(UTC),
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_analytics_relation_sets_code_version",
            set_={
                "description": stmt.excluded.description,
                "parameters": stmt.excluded.parameters,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        session.execute(stmt)
        ensured += 1

    session.execute(update(RelationSet).values(is_active=False))
    basic = session.scalar(
        select(RelationSet).where(RelationSet.code == "basic_relations", RelationSet.version == 1)
    )
    activated = 0
    if basic:
        basic.is_active = True
        activated = 1
    session.flush()
    return {"ensured": ensured, "activated": activated}


def _upsert_input(
    session: Session,
    *,
    code: str,
    input_family: str,
    subject_type: str,
    subject_id: int,
    feature_key: str,
    transform: str,
    alignment_policy: str,
    display_name: str,
    metadata: dict | None = None,
) -> None:
    stmt = insert(RelationInput).values(
        code=code,
        input_family=input_family,
        subject_type=subject_type,
        subject_id=subject_id,
        feature_key=feature_key,
        transform=transform,
        alignment_policy=alignment_policy,
        display_name=display_name,
        is_active=True,
        extra=metadata or {},
        updated_at=datetime.now(UTC),
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_analytics_relation_inputs_code",
        set_={
            "input_family": stmt.excluded.input_family,
            "subject_type": stmt.excluded.subject_type,
            "subject_id": stmt.excluded.subject_id,
            "feature_key": stmt.excluded.feature_key,
            "transform": stmt.excluded.transform,
            "alignment_policy": stmt.excluded.alignment_policy,
            "display_name": stmt.excluded.display_name,
            "is_active": True,
            "extra": stmt.excluded.extra,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)


def seed_relation_inputs(session: Session) -> dict[str, int]:
    """Ensure default inputs: active instruments → log_return_1d; documented series transforms."""
    instruments = list(
        session.scalars(select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.symbol))
    )
    series_list = list(session.scalars(select(Series).where(Series.is_active.is_(True)).order_by(Series.code)))

    instrument_count = 0
    for inst in instruments:
        code = f"instrument:{inst.symbol}:{INSTRUMENT_FEATURE_KEY}"
        _upsert_input(
            session,
            code=code,
            input_family="instrument_feature",
            subject_type="instrument",
            subject_id=inst.id,
            feature_key=INSTRUMENT_FEATURE_KEY,
            transform=INSTRUMENT_TRANSFORM,
            alignment_policy=INSTRUMENT_ALIGNMENT,
            display_name=f"{inst.symbol} {INSTRUMENT_FEATURE_KEY}",
            metadata={"symbol": inst.symbol},
        )
        instrument_count += 1

    series_count = 0
    for series in series_list:
        cfg = SERIES_INPUT_TRANSFORMS.get(series.code)
        if cfg is None:
            continue
        code = f"series:{series.code}:{cfg['feature_key']}"
        _upsert_input(
            session,
            code=code,
            input_family="series_feature",
            subject_type="series",
            subject_id=series.id,
            feature_key=cfg["feature_key"],
            transform=cfg["transform"],
            alignment_policy=cfg["alignment_policy"],
            display_name=f"{series.code} {cfg['feature_key']}",
            metadata={"series_code": series.code},
        )
        series_count += 1

    session.flush()
    return {"instruments": instrument_count, "series": series_count}
