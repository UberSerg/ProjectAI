"""Idempotent seed for pit_daily_core v1."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetSpec
from app.modules.learning.dataset_config import PIT_DAILY_CORE_V1


def seed_dataset_specs(session: Session) -> dict[str, int]:
    definition = PIT_DAILY_CORE_V1
    stmt = insert(DatasetSpec).values(
        code=definition["code"],
        version=definition["version"],
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
    session.execute(update(DatasetSpec).where(DatasetSpec.code == definition["code"]).values(is_active=False))
    row = session.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == definition["code"], DatasetSpec.version == definition["version"]
        )
    )
    activated = 0
    if row is not None:
        row.is_active = True
        activated = 1
    session.flush()
    return {"ensured": 1, "activated": activated}
