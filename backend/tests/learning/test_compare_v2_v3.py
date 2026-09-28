"""Fair V2↔V3 comparison contract tests (coverage, not alpha)."""

from __future__ import annotations

from app.modules.learning.application.compare_v2_v3 import compare_v2_v3_builds
from app.modules.learning.application.research_eval import assert_fair_compare_contract
from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_ACTIVE_VERSION,
    PIT_DAILY_CORE_V2,
    PIT_DAILY_CORE_V3,
)


def test_fair_compare_contract_universe_only_differs() -> None:
    fair = assert_fair_compare_contract()
    assert fair["pins_match"] is True
    assert PIT_DAILY_CORE_V2["universe_policy"] != PIT_DAILY_CORE_V3["universe_policy"]
    assert PIT_DAILY_CORE_ACTIVE_VERSION == 1


def test_compare_reuses_existing_runs_without_activating(core_db, monkeypatch) -> None:
    """Reuse existing SUCCESS runs when present; never flip ACTIVE version."""
    from sqlalchemy import select

    from app.infrastructure.learning.models import DatasetRun, DatasetSpec
    from app.modules.learning.application.seed import seed_dataset_specs

    seed_dataset_specs(core_db)
    active = core_db.scalar(select(DatasetSpec).where(DatasetSpec.is_active.is_(True)))
    assert active is not None
    assert active.version == 1

    v2_spec = core_db.scalar(
        select(DatasetSpec).where(DatasetSpec.code == "pit_daily_core", DatasetSpec.version == 2)
    )
    v3_spec = core_db.scalar(
        select(DatasetSpec).where(DatasetSpec.code == "pit_daily_core", DatasetSpec.version == 3)
    )
    assert v2_spec is not None and v3_spec is not None

    v2_run = core_db.scalar(
        select(DatasetRun)
        .where(DatasetRun.dataset_spec_id == v2_spec.id, DatasetRun.status.in_(("SUCCESS", "WARNING")))
        .order_by(DatasetRun.id.desc())
    )
    v3_run = core_db.scalar(
        select(DatasetRun)
        .where(DatasetRun.dataset_spec_id == v3_spec.id, DatasetRun.status.in_(("SUCCESS", "WARNING")))
        .order_by(DatasetRun.id.desc())
    )
    if v2_run is None or v3_run is None:
        # No existing paired runs in this DB — contract unit test above still covers fairness.
        return
    if v2_run.date_from is None or v2_run.date_to is None:
        return
    if v2_run.date_from != v3_run.date_from or v2_run.date_to != v3_run.date_to:
        # Need matching windows for fair reuse.
        return

    artifact = compare_v2_v3_builds(
        core_db,
        date_from=v2_run.date_from,
        date_to=v2_run.date_to,
        v2_run_id=v2_run.id,
        v3_run_id=v3_run.id,
        rebuild=False,
    )
    assert artifact["label"] == "EXPERIMENTAL_V3_RESEARCH"
    assert artifact["active_dataset_spec"]["isolation_ok"] is True
    assert artifact["active_dataset_spec"]["after"]["version"] == 1
    assert "sample_diff" in artifact
    assert "interpretation" in artifact
    assert not any("wins" in x.lower() for x in artifact["interpretation"])


def test_research_loader_allows_v2_v3_not_v1(core_db) -> None:
    from app.modules.learning.application.seed import seed_dataset_specs
    from app.modules.prediction.application.research_dataset_loader import (
        ALLOWED_RESEARCH_VERSIONS,
        ResearchDatasetError,
        resolve_research_dataset_run,
    )

    seed_dataset_specs(core_db)
    assert ALLOWED_RESEARCH_VERSIONS == frozenset({2, 3})
    try:
        resolve_research_dataset_run(core_db, dataset_spec_version=1)
        raise AssertionError("expected ResearchDatasetError for v1")
    except ResearchDatasetError as exc:
        assert "allows versions" in str(exc)


def test_research_loader_does_not_touch_candidate_pins() -> None:
    from app.modules.learning.dataset_config import PIT_DAILY_CORE_V2_VERSION
    from app.modules.prediction.application.research_runner import (
        CANDIDATE_V0_LOCKED_VERSION,
        CANDIDATE_V1_LOCKED_VERSION,
    )
    from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
    from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG

    assert CANDIDATE_V0_CONFIG.dataset_spec_version == PIT_DAILY_CORE_V2_VERSION
    assert CANDIDATE_V1_RANKER_CONFIG.dataset_spec_version == PIT_DAILY_CORE_V2_VERSION
    assert CANDIDATE_V0_LOCKED_VERSION == 2
    assert CANDIDATE_V1_LOCKED_VERSION == 2
    assert PIT_DAILY_CORE_ACTIVE_VERSION == 1


def test_experimental_oos_forbids_registry_persist(core_db) -> None:
    import pytest

    from app.modules.prediction.application.research_runner import run_experimental_v2_v3_oos

    with pytest.raises(ValueError, match="must not persist"):
        run_experimental_v2_v3_oos(
            core_db,
            dataset_spec_version=3,
            persist_registry=True,
        )
