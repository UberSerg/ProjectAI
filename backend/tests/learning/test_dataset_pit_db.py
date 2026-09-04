"""DB integration for Dataset/PIT Phase 1: spec seed, version pins, sample persist."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import FeatureSet
from app.infrastructure.learning.models import DatasetRun, DatasetSampleDaily, DatasetSpec
from app.infrastructure.learning.repository import insert_dataset_samples, sample_row
from app.infrastructure.market.models import Instrument
from app.modules.analytics.application.resolve import resolve_feature_set
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.learning.application.hash_util import sample_content_hash, sample_values_hash
from app.modules.learning.application.seed import seed_dataset_specs
from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_VERSION,
    RELATION_CONTEXTS_V1,
    relation_feature_names,
)


def _ensure_version(session: Session, code: str, version: int) -> FeatureSet:
    existing = session.scalar(select(FeatureSet).where(FeatureSet.code == code, FeatureSet.version == version))
    if existing:
        return existing
    row = FeatureSet(
        code=code,
        version=version,
        description=f"{code} v{version} pin test",
        parameters={},
        is_active=False,
        updated_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def _activate_version(session: Session, code: str, version: int) -> FeatureSet:
    session.execute(update(FeatureSet).where(FeatureSet.code == code).values(is_active=False))
    session.flush()
    row = session.scalar(select(FeatureSet).where(FeatureSet.code == code, FeatureSet.version == version))
    assert row is not None
    row.is_active = True
    session.flush()
    return row


def test_seed_dataset_spec_idempotent(core_db: Session) -> None:
    first = seed_dataset_specs(core_db)
    second = seed_dataset_specs(core_db)
    assert first["ensured"] == 2
    assert second["ensured"] == 2
    rows = list(
        core_db.scalars(
            select(DatasetSpec)
            .where(DatasetSpec.code == PIT_DAILY_CORE_CODE)
            .order_by(DatasetSpec.version)
        )
    )
    assert len(rows) == 2
    spec = rows[0]
    assert spec.version == PIT_DAILY_CORE_VERSION
    assert spec.is_active is True
    v2 = rows[1]
    assert v2.version == 2
    assert v2.is_active is False
    assert v2.basic_feature_set_version == 2
    assert v2.technical_feature_set_version == 2
    assert v2.technical_model_version == 2
    assert v2.relation_set_version == 2
    assert v2.label_spec.get("price_basis") == "mechanical_adjusted"
    assert spec.basic_feature_set_code == "basic_daily"
    assert spec.basic_feature_set_version == 1
    assert spec.technical_feature_set_code == "technical_daily"
    assert spec.technical_feature_set_version == 1
    assert spec.technical_model_code == "rules"
    assert spec.technical_model_version == 1
    assert spec.relation_set_code == "basic_relations"
    assert spec.relation_set_version == 1
    roles = {item["name"]: item["role"] for item in spec.feature_manifest}
    assert roles["return_5d"] == "feature"
    assert roles["forward_return_5d"] == "label"
    assert "forward_return_5d" not in {n for n, r in roles.items() if r == "feature"}
    for name in relation_feature_names(RELATION_CONTEXTS_V1):
        assert roles[name] == "feature"
    assert spec.quality_policy["relation_pit_field"] == "snapshot.as_of_date"
    assert spec.quality_policy["relation_run_source_watermark"] == "compute_lineage_not_pit"
    assert spec.quality_policy["relation_missing_means"] == "no_usable_context_for_sample"


def test_pinned_feature_set_ignores_active_v2(core_db: Session) -> None:
    seed_feature_sets(core_db)
    v1 = resolve_feature_set(core_db, "basic_daily", 1)
    assert v1.version == 1
    _ensure_version(core_db, "basic_daily", 2)
    _activate_version(core_db, "basic_daily", 2)

    active = resolve_feature_set(core_db, "basic_daily", None)
    assert active.version == 2
    pinned = resolve_feature_set(core_db, "basic_daily", 1)
    assert pinned.id == v1.id
    assert pinned.version == 1

    tech_v1 = resolve_feature_set(core_db, "technical_daily", 1)
    _ensure_version(core_db, "technical_daily", 2)
    _activate_version(core_db, "technical_daily", 2)
    assert resolve_feature_set(core_db, "technical_daily", None).version == 2
    assert resolve_feature_set(core_db, "technical_daily", 1).id == tech_v1.id


def test_sample_persist_round_trip(core_db: Session) -> None:
    seed_dataset_specs(core_db)
    spec = core_db.scalar(select(DatasetSpec).where(DatasetSpec.is_active.is_(True)))
    assert spec is not None
    inst = core_db.scalar(select(Instrument).where(Instrument.is_active.is_(True)))
    if inst is None:
        inst = Instrument(
            symbol="PITTEST",
            name="PIT Test",
            asset_class="equity",
            exchange="MOEX",
            currency="RUB",
            is_active=True,
        )
        core_db.add(inst)
        core_db.flush()

    run = DatasetRun(
        dataset_spec_id=spec.id,
        date_from=date(2024, 6, 1),
        date_to=date(2024, 6, 1),
        status="SUCCESS",
        pit_status="PASS",
        samples_total=1,
        dataset_hash="abc",
    )
    core_db.add(run)
    core_db.flush()

    features = {"return_5d": 0.02, "rsi14": 55.0, "technical_score": 0.3}
    labels = {"forward_return_5d": 0.04, "target_date_5d": "2024-06-10"}
    inserted = insert_dataset_samples(
        core_db,
        [
            sample_row(
                dataset_run_id=run.id,
                dataset_spec_id=spec.id,
                instrument_id=inst.id,
                as_of_date=date(2024, 6, 1),
                features=features,
                labels=labels,
                feature_quality={"feature_state_valid": True, "technical_available": True},
                label_quality={"label_valid": {"5d": True}},
                training_eligibility={"training_eligible_5d": True},
                lineage={
                    "basic_feature_set_code": "basic_daily",
                    "basic_feature_set_version": 1,
                    "technical_feature_set_code": "technical_daily",
                    "technical_feature_set_version": 1,
                    "technical_model_code": "rules",
                    "technical_model_version": 1,
                },
                content_hash="hash1",
            )
        ],
    )
    assert inserted == 1
    row = core_db.scalar(
        select(DatasetSampleDaily).where(
            DatasetSampleDaily.dataset_run_id == run.id,
            DatasetSampleDaily.instrument_id == inst.id,
        )
    )
    assert row is not None
    assert row.features["return_5d"] == 0.02
    assert "forward_return_5d" not in row.features
    assert row.labels["forward_return_5d"] == 0.04
    run_count = core_db.scalar(
        select(func.count())
        .select_from(DatasetSampleDaily)
        .where(DatasetSampleDaily.dataset_run_id == run.id)
    )
    assert run_count == 1


def test_seed_freezes_after_successful_run(core_db: Session) -> None:
    seed_dataset_specs(core_db)
    spec = core_db.scalar(select(DatasetSpec).where(DatasetSpec.is_active.is_(True)))
    assert spec is not None
    marker = dict(spec.quality_policy or {})
    marker["audit_marker"] = "keep"
    spec.quality_policy = marker
    core_db.flush()

    run = DatasetRun(
        dataset_spec_id=spec.id,
        date_from=date(2024, 1, 1),
        date_to=date(2024, 1, 2),
        status="SUCCESS",
        pit_status="PASS",
        samples_total=1,
        dataset_hash="frozen",
    )
    core_db.add(run)
    core_db.flush()

    result = seed_dataset_specs(core_db)
    assert result.get("frozen") is True
    core_db.refresh(spec)
    assert spec.quality_policy.get("audit_marker") == "keep"


def test_values_hash_ignores_surrogate_ids() -> None:
    features = {"return_5d": 0.02, "rel_imoex_w60_pearson": 0.3}
    labels = {"forward_return_5d": 0.04}
    a = sample_values_hash(instrument_id=1, as_of_date="2024-06-01", features=features, labels=labels)
    b = sample_values_hash(instrument_id=1, as_of_date="2024-06-01", features=features, labels=labels)
    assert a == b
    h1 = sample_content_hash(
        instrument_id=1,
        as_of_date="2024-06-01",
        features=features,
        labels=labels,
        lineage_identity={"basic_feature_id": 1},
    )
    h2 = sample_content_hash(
        instrument_id=1,
        as_of_date="2024-06-01",
        features=features,
        labels=labels,
        lineage_identity={"basic_feature_id": 99},
    )
    assert h1 != h2
    assert a == sample_values_hash(
        instrument_id=1, as_of_date="2024-06-01", features=features, labels=labels
    )
