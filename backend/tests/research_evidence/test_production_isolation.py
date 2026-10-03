"""Research Evidence Engine V1 must not move production pins."""

from __future__ import annotations

from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_ACTIVE_VERSION,
    PIT_DAILY_CORE_V2_VERSION,
)
from app.modules.prediction.candidate_config import CandidateV0Config
from app.modules.prediction.candidate_v1_config import CandidateV1RankerConfig


def test_active_dataset_spec_remains_v1() -> None:
    assert PIT_DAILY_CORE_ACTIVE_VERSION == 1


def test_candidate_v0_dataset_remains_v2() -> None:
    assert CandidateV0Config().dataset_spec_version == PIT_DAILY_CORE_V2_VERSION
    assert CandidateV0Config().dataset_spec_version == 2


def test_candidate_v1_dataset_remains_v2() -> None:
    assert CandidateV1RankerConfig().dataset_spec_version == PIT_DAILY_CORE_V2_VERSION
    assert CandidateV1RankerConfig().dataset_spec_version == 2


def test_research_evidence_source_forbids_registry_persist_literal() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "app" / "modules" / "research_evidence"
    if not root.exists():
        return
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
    assert "persist_registry=True" not in text
    assert "persist_registry = True" not in text
