"""Production isolation guards for Intelligence Stack V1."""

from __future__ import annotations

from typing import Any

from app.modules.learning.dataset_config import PIT_DAILY_CORE_ACTIVE_VERSION
from app.modules.prediction.candidate_config import CandidateV0Config
from app.modules.prediction.candidate_v1_config import CandidateV1RankerConfig

INTELLIGENCE_STACK_VERSION = "intelligence_stack_v1"
EXPECTED_ACTIVE_DATASET = 1
EXPECTED_CANDIDATE_DATASET = 2


def production_isolation_report() -> dict[str, Any]:
    """Snapshot of pins that intelligence must not mutate."""
    v0 = CandidateV0Config()
    v1 = CandidateV1RankerConfig()
    return {
        "intelligence_stack_version": INTELLIGENCE_STACK_VERSION,
        "persist_registry": False,
        "candidate_promotion": False,
        "shadow_policy_switch": False,
        "daily_decision_switch": False,
        "broker_execution": False,
        "pit_daily_core_active_version": PIT_DAILY_CORE_ACTIVE_VERSION,
        "candidate_v0_dataset_spec_version": v0.dataset_spec_version,
        "candidate_v1_dataset_spec_version": v1.dataset_spec_version,
        "active_dataset_unchanged": PIT_DAILY_CORE_ACTIVE_VERSION == EXPECTED_ACTIVE_DATASET,
        "candidate_pins_unchanged": (
            v0.dataset_spec_version == EXPECTED_CANDIDATE_DATASET
            and v1.dataset_spec_version == EXPECTED_CANDIDATE_DATASET
        ),
    }


def assert_production_isolation() -> None:
    report = production_isolation_report()
    if not report["active_dataset_unchanged"]:
        raise RuntimeError(
            f"ACTIVE DatasetSpec must remain {EXPECTED_ACTIVE_DATASET}, "
            f"got {report['pit_daily_core_active_version']}"
        )
    if not report["candidate_pins_unchanged"]:
        raise RuntimeError("Candidate V0/V1 dataset pins must remain Dataset V2")
