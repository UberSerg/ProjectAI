"""Idempotent seed for pit_daily_core versions.

After a successful DatasetRun exists for a code+version, semantic fields
for that version are not overwritten — require a new dataset version instead.

Active released contract remains pit_daily_core v1; V2 is seeded but not activated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetRun, DatasetSpec
from app.modules.learning.dataset_config import (
    DATASET_SPEC_DEFINITIONS,
    PIT_DAILY_CORE_ACTIVE_VERSION,
    PIT_DAILY_CORE_CODE,
)


def _has_successful_run(session: Session, code: str, version: int) -> bool:
    return (
        session.scalar(
            select(DatasetRun.id)
            .join(DatasetSpec, DatasetRun.dataset_spec_id == DatasetSpec.id)
            .where(
                DatasetSpec.code == code,
                DatasetSpec.version == version,
                DatasetRun.status == "SUCCESS",
            )
            .limit(1)
        )
        is not None
    )


def _upsert_definition(session: Session, definition: dict[str, Any]) -> dict[str, Any]:
    code = definition["code"]
    version = definition["version"]
    existing = session.scalar(select(DatasetSpec).where(DatasetSpec.code == code, DatasetSpec.version == version))
    if existing is not None and _has_successful_run(session, code, version):
        return {"ensured": 1, "frozen": True, "version": version}

    stmt = insert(DatasetSpec).values(
        code=code,
        version=version,
        description=definition["description"],
        feature_manifest=definition["feature_manifest"],
        relation_contexts=definition["relation_contexts"],
        label_spec=definition["label_spec"],
        quality_policy=definition["quality_policy"],
        basic_feature_set_code=definition["basic_feature_set_code"],
        basic_feature_set_version=definition["basic_feature_set_version"],
        technical_feature_set_code=definition["technical_feature_set_code"],
        technical_feature_set_version=definition["technical_feature_set_version"],
        technical_model_code=definition["technical_model_code"],
        technical_model_version=definition["technical_model_version"],
        technical_model_config_hash=definition["technical_model_config_hash"],
        relation_set_code=definition["relation_set_code"],
        relation_set_version=definition["relation_set_version"],
        universe_policy=definition["universe_policy"],
        parameters=definition["parameters"],
        is_active=False,
        updated_at=datetime.now(UTC),
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_learning_dataset_specs_code_version",
        set_={
            "description": stmt.excluded.description,
            "feature_manifest": stmt.excluded.feature_manifest,
            "relation_contexts": stmt.excluded.relation_contexts,
            "label_spec": stmt.excluded.label_spec,
            "quality_policy": stmt.excluded.quality_policy,
            "basic_feature_set_code": stmt.excluded.basic_feature_set_code,
            "basic_feature_set_version": stmt.excluded.basic_feature_set_version,
            "technical_feature_set_code": stmt.excluded.technical_feature_set_code,
            "technical_feature_set_version": stmt.excluded.technical_feature_set_version,
            "technical_model_code": stmt.excluded.technical_model_code,
            "technical_model_version": stmt.excluded.technical_model_version,
            "technical_model_config_hash": stmt.excluded.technical_model_config_hash,
            "relation_set_code": stmt.excluded.relation_set_code,
            "relation_set_version": stmt.excluded.relation_set_version,
            "universe_policy": stmt.excluded.universe_policy,
            "parameters": stmt.excluded.parameters,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)
    return {"ensured": 1, "frozen": False, "version": version}


def seed_dataset_specs(session: Session) -> dict[str, Any]:
    results = [_upsert_definition(session, definition) for definition in DATASET_SPEC_DEFINITIONS]
    session.execute(update(DatasetSpec).where(DatasetSpec.code == PIT_DAILY_CORE_CODE).values(is_active=False))
    active = session.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == PIT_DAILY_CORE_CODE,
            DatasetSpec.version == PIT_DAILY_CORE_ACTIVE_VERSION,
        )
    )
    activated = 0
    if active is not None:
        active.is_active = True
        activated = 1
    session.flush()
    return {
        "ensured": sum(item["ensured"] for item in results),
        "activated": activated,
        "active_version": PIT_DAILY_CORE_ACTIVE_VERSION,
        "versions": results,
        "frozen": any(item["frozen"] for item in results),
    }
