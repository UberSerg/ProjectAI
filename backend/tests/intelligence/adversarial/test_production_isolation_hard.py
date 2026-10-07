"""Prove intelligence paths cannot mutate production Candidate / Shadow / broker."""

from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path

import pytest

from app.modules.intelligence.contracts.snapshot import IntelligenceSnapshotV1
from app.modules.intelligence.isolation import (
    EXPECTED_ACTIVE_DATASET,
    EXPECTED_CANDIDATE_DATASET,
    INTELLIGENCE_STACK_VERSION,
    assert_production_isolation,
    production_isolation_report,
)
from app.modules.learning.dataset_config import PIT_DAILY_CORE_ACTIVE_VERSION
from app.modules.prediction.candidate_config import CandidateV0Config
from app.modules.prediction.candidate_v1_config import CandidateV1RankerConfig
from tests.intelligence.adversarial._helpers import (
    isolation_flags_must_be_false,
    scan_intelligence_for_forbidden_production_mutations,
)


def test_isolation_report_pins_and_flags() -> None:
    before = production_isolation_report()
    isolation_flags_must_be_false(before)
    assert before["intelligence_stack_version"] == INTELLIGENCE_STACK_VERSION
    assert before["pit_daily_core_active_version"] == EXPECTED_ACTIVE_DATASET
    assert before["candidate_v0_dataset_spec_version"] == EXPECTED_CANDIDATE_DATASET
    assert before["candidate_v1_dataset_spec_version"] == EXPECTED_CANDIDATE_DATASET
    assert before["active_dataset_unchanged"] is True
    assert before["candidate_pins_unchanged"] is True
    assert_production_isolation()


def test_isolation_stable_across_snapshot_construction() -> None:
    before = production_isolation_report()
    snap = IntelligenceSnapshotV1(
        instrument_id=1,
        symbol="SBER",
        as_of=date(2026, 7, 1),
        limitations=("advisory_only",),
        production_isolation=production_isolation_report(),
    )
    after = production_isolation_report()
    assert before == after
    assert snap.production_isolation["persist_registry"] is False
    assert snap.production_isolation["broker_execution"] is False
    assert snap.production_isolation["shadow_policy_switch"] is False
    assert snap.production_isolation["daily_decision_switch"] is False
    assert snap.production_isolation["candidate_promotion"] is False


def test_active_dataset_and_candidate_pins_untouched() -> None:
    assert PIT_DAILY_CORE_ACTIVE_VERSION == 1
    assert CandidateV0Config().dataset_spec_version == 2
    assert CandidateV1RankerConfig().dataset_spec_version == 2
    # Re-read after importing intelligence package surface.
    importlib.import_module("app.modules.intelligence")
    importlib.import_module("app.modules.intelligence.isolation")
    assert PIT_DAILY_CORE_ACTIVE_VERSION == EXPECTED_ACTIVE_DATASET
    assert CandidateV0Config().dataset_spec_version == EXPECTED_CANDIDATE_DATASET
    assert CandidateV1RankerConfig().dataset_spec_version == EXPECTED_CANDIDATE_DATASET


def test_static_scan_no_production_mutators_in_intelligence_package() -> None:
    findings = scan_intelligence_for_forbidden_production_mutations()
    assert findings == [], f"forbidden production touchpoints: {findings}"


def test_intelligence_package_has_no_broker_or_personal_operation_imports() -> None:
    root = (
        Path(__file__).resolve().parents[3] / "app" / "modules" / "intelligence"
    )
    banned_substrings = (
        "PersonalOperation",
        "create_operation(",
        "broker_execution",
        "promote_candidate",
        "switch_shadow",
        "activate_dataset",
    )
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # isolation.py may mention flags as False constants — allow report keys only.
        if path.name == "isolation.py":
            continue
        for token in banned_substrings:
            if token in text:
                offenders.append(f"{path.name}:{token}")
    assert offenders == [], offenders


def test_assert_production_isolation_fails_if_active_pin_drifted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.intelligence.isolation as iso

    monkeypatch.setattr(iso, "PIT_DAILY_CORE_ACTIVE_VERSION", 999)
    with pytest.raises(RuntimeError, match="ACTIVE DatasetSpec"):
        iso.assert_production_isolation()
