"""DB tests for Candidate V0 Dataset pin (self-contained for CI)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetRun, DatasetSpec
from app.modules.learning.application.seed import seed_dataset_specs
from app.modules.prediction.application.dataset_loader import DatasetPinError, resolve_pinned_dataset_run
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, CandidateV0Config


def _v2_spec(session: Session) -> DatasetSpec:
    seed_dataset_specs(session)
    spec = session.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == CANDIDATE_V0_CONFIG.dataset_spec_code,
            DatasetSpec.version == CANDIDATE_V0_CONFIG.dataset_spec_version,
        )
    )
    assert spec is not None
    return spec


def _success_run(
    session: Session,
    *,
    spec: DatasetSpec,
    values_hash: str,
    dataset_hash: str,
) -> DatasetRun:
    run = DatasetRun(
        dataset_spec_id=spec.id,
        date_from=date(2014, 1, 6),
        date_to=date(2026, 9, 2),
        status="SUCCESS",
        pit_status="PASS",
        samples_total=1,
        dataset_hash=dataset_hash,
        manifest={"values_hash": values_hash},
    )
    session.add(run)
    session.flush()
    return run


def test_values_hash_mismatch_rejects(core_db: Session) -> None:
    spec = _v2_spec(core_db)
    run = _success_run(
        core_db,
        spec=spec,
        values_hash=CANDIDATE_V0_CONFIG.required_values_hash,
        dataset_hash=CANDIDATE_V0_CONFIG.required_dataset_hash,
    )
    bad = CandidateV0Config(
        preferred_dataset_run_id=run.id,
        required_values_hash="0" * 64,
        required_dataset_hash=CANDIDATE_V0_CONFIG.required_dataset_hash,
    )
    with pytest.raises(DatasetPinError, match="values_hash mismatch"):
        resolve_pinned_dataset_run(core_db, bad)


def test_pinned_run_matches_canonical_hash(core_db: Session) -> None:
    spec = _v2_spec(core_db)
    run = _success_run(
        core_db,
        spec=spec,
        values_hash=CANDIDATE_V0_CONFIG.required_values_hash,
        dataset_hash=CANDIDATE_V0_CONFIG.required_dataset_hash,
    )
    cfg = CandidateV0Config(preferred_dataset_run_id=run.id)
    resolved = resolve_pinned_dataset_run(core_db, cfg)
    assert resolved.id == run.id
    assert (resolved.manifest or {}).get("values_hash") == CANDIDATE_V0_CONFIG.required_values_hash
    assert resolved.dataset_hash == CANDIDATE_V0_CONFIG.required_dataset_hash
