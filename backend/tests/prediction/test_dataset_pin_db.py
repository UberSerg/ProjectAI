"""DB tests for Candidate V0 Dataset pin."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.modules.prediction.application.dataset_loader import DatasetPinError, resolve_pinned_dataset_run
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, CandidateV0Config


def test_values_hash_mismatch_rejects(core_db: Session) -> None:
    bad = CandidateV0Config(required_values_hash="0" * 64)
    with pytest.raises(DatasetPinError, match="values_hash mismatch"):
        resolve_pinned_dataset_run(core_db, bad)


def test_pinned_run_matches_canonical_hash(core_db: Session) -> None:
    run = resolve_pinned_dataset_run(core_db, CANDIDATE_V0_CONFIG)
    assert (run.manifest or {}).get("values_hash") == CANDIDATE_V0_CONFIG.required_values_hash
    assert run.dataset_hash == CANDIDATE_V0_CONFIG.required_dataset_hash
