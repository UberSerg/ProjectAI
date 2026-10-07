"""Experiment identity + isolation for Intelligence Research V1."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.modules.intelligence.isolation import EXPECTED_ACTIVE_DATASET, EXPECTED_CANDIDATE_DATASET
from app.modules.intelligence.research.constants import (
    EVALUATION_WORDING,
    EXPERIMENT_NAME,
    EXPERIMENT_VERSION,
)
from app.modules.intelligence.research.experiment import (
    IntelligenceResearchExperimentV1,
    fingerprint_identity,
)

_KW = dict(
    date_from="2022-04-01",
    date_to="2026-10-07",
    model_seed=42,
)


def test_deterministic_fingerprint() -> None:
    a = IntelligenceResearchExperimentV1(**_KW)
    b = IntelligenceResearchExperimentV1(**_KW)
    assert a.experiment_fingerprint == b.experiment_fingerprint
    assert len(a.experiment_fingerprint) == 64
    identity = a.identity_payload()
    assert identity["experiment_version"] == EXPERIMENT_VERSION
    assert identity["experiment_name"] == EXPERIMENT_NAME
    assert identity["is_dataset_v5"] is False
    assert identity["retunes_v4"] is False
    assert identity["retunes_canonical_campaign"] is False
    assert identity["persist_registry"] is False


def test_key_order_independence() -> None:
    identity = IntelligenceResearchExperimentV1(**_KW).identity_payload()
    reversed_keys = dict(reversed(list(identity.items())))
    assert fingerprint_identity(identity) == fingerprint_identity(reversed_keys)


def test_runtime_timestamp_not_in_identity() -> None:
    stamped = IntelligenceResearchExperimentV1(
        **_KW, created_at=datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    )
    plain = IntelligenceResearchExperimentV1(**_KW, created_at=None)
    assert "created_at" not in stamped.identity_payload()
    assert stamped.experiment_fingerprint == plain.experiment_fingerprint
    record = stamped.to_record()
    assert record["created_at"] is not None
    assert record["is_dataset_v5"] is False
    assert record["research_only"] is True
    assert EVALUATION_WORDING in record["evaluation_wording"]
    blob = str(record).lower()
    assert "dataset v5" not in blob
    assert "pristine final holdout" not in blob
    assert "live ready" not in blob


def test_persist_registry_true_rejected() -> None:
    with pytest.raises(ValueError, match="persist_registry"):
        IntelligenceResearchExperimentV1(**_KW, persist_registry=True)


def test_production_isolation_pins_unchanged() -> None:
    record = IntelligenceResearchExperimentV1(**_KW).to_record()
    iso = record["production_isolation"]
    assert iso["pit_daily_core_active_version"] == EXPECTED_ACTIVE_DATASET
    assert iso["candidate_v0_dataset_spec_version"] == EXPECTED_CANDIDATE_DATASET
    assert iso["candidate_v1_dataset_spec_version"] == EXPECTED_CANDIDATE_DATASET
    assert iso["candidate_promotion"] is False
    assert iso["persist_registry"] is False


def test_feature_groups_include_intelligence_packs() -> None:
    groups = IntelligenceResearchExperimentV1(**_KW).identity_payload()[
        "feature_group_definitions"
    ]
    assert "BASE" in groups
    assert "BASE+INTRADAY" in groups
    assert "BASE+RICH_FUNDAMENTAL" in groups
    assert "BASE+EVENT" in groups
    assert "BASE+MACRO" in groups
    assert "INTELLIGENCE_FULL" in groups
    assert "V4_FULL" not in groups  # separate experiment identity
    assert date.fromisoformat(_KW["date_from"]) == date(2022, 4, 1)
