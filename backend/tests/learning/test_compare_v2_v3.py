"""Fair V2↔V3 comparison contract tests (coverage, not alpha)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.learning.application.compare_v2_v3 import (
    CompareContractError,
    _require_spec,
    compare_v2_v3_builds,
)
from app.modules.learning.application.research_eval import (
    FairCompareError,
    assert_fair_compare_contract,
    assert_fair_model_run_contract,
)
from app.modules.learning.application.seed import seed_dataset_specs, snapshot_dataset_spec_flags
from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_ACTIVE_VERSION,
    PIT_DAILY_CORE_V2,
    PIT_DAILY_CORE_V3,
)
from app.modules.prediction.application.research_runner import (
    CANDIDATE_V0_LOCKED_VERSION,
    CANDIDATE_V1_LOCKED_VERSION,
)
from app.modules.prediction.candidate_config import CATBOOST_HYPERPARAMETERS, RANDOM_SEED


def test_fair_compare_contract_universe_only_differs() -> None:
    fair = assert_fair_compare_contract()
    assert fair["pins_match"] is True
    assert PIT_DAILY_CORE_V2["universe_policy"] != PIT_DAILY_CORE_V3["universe_policy"]
    assert PIT_DAILY_CORE_ACTIVE_VERSION == 1


def _make_run(*, run_id: int, date_from: date, date_to: date, status: str = "SUCCESS") -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        dataset_spec_id="x",
    )


def test_fair_model_contract_matching_window() -> None:
    spec_v2 = SimpleNamespace(code="pit_daily_core", version=2)
    spec_v3 = SimpleNamespace(code="pit_daily_core", version=3)
    cut = date(2024, 6, 1)
    fair = assert_fair_model_run_contract(
        _make_run(run_id=1, date_from=date(2024, 1, 1), date_to=date(2024, 12, 31)),
        _make_run(run_id=2, date_from=date(2024, 1, 1), date_to=date(2024, 12, 31)),
        oos_start=cut,
        hyperparameters=dict(CATBOOST_HYPERPARAMETERS),
        random_seed=RANDOM_SEED,
        spec_v2=spec_v2,
        spec_v3=spec_v3,
    )
    assert fair["fair_contract_pass"] is True
    assert fair["random_seed"] == RANDOM_SEED
    assert fair["hyperparameters"]["random_seed"] == RANDOM_SEED


def test_fair_model_contract_rejects_mismatched_from() -> None:
    spec_v2 = SimpleNamespace(code="pit_daily_core", version=2)
    spec_v3 = SimpleNamespace(code="pit_daily_core", version=3)
    with pytest.raises(FairCompareError, match="mismatched run windows"):
        assert_fair_model_run_contract(
            _make_run(run_id=1, date_from=date(2023, 1, 1), date_to=date(2024, 12, 31)),
            _make_run(run_id=2, date_from=date(2024, 1, 1), date_to=date(2024, 12, 31)),
            oos_start=date(2024, 6, 1),
            hyperparameters=dict(CATBOOST_HYPERPARAMETERS),
            random_seed=RANDOM_SEED,
            spec_v2=spec_v2,
            spec_v3=spec_v3,
        )


def test_fair_model_contract_rejects_mismatched_to() -> None:
    spec_v2 = SimpleNamespace(code="pit_daily_core", version=2)
    spec_v3 = SimpleNamespace(code="pit_daily_core", version=3)
    with pytest.raises(FairCompareError, match="mismatched run windows"):
        assert_fair_model_run_contract(
            _make_run(run_id=1, date_from=date(2024, 1, 1), date_to=date(2024, 6, 30)),
            _make_run(run_id=2, date_from=date(2024, 1, 1), date_to=date(2024, 12, 31)),
            oos_start=date(2024, 3, 1),
            hyperparameters=dict(CATBOOST_HYPERPARAMETERS),
            random_seed=RANDOM_SEED,
            spec_v2=spec_v2,
            spec_v3=spec_v3,
        )


def test_fair_model_contract_rejects_wrong_spec_version() -> None:
    with pytest.raises(FairCompareError, match="not pit_daily_core v3"):
        assert_fair_model_run_contract(
            _make_run(run_id=1, date_from=date(2024, 1, 1), date_to=date(2024, 12, 31)),
            _make_run(run_id=2, date_from=date(2024, 1, 1), date_to=date(2024, 12, 31)),
            oos_start=date(2024, 6, 1),
            hyperparameters=dict(CATBOOST_HYPERPARAMETERS),
            random_seed=RANDOM_SEED,
            spec_v2=SimpleNamespace(code="pit_daily_core", version=2),
            spec_v3=SimpleNamespace(code="pit_daily_core", version=2),
        )


def test_fair_model_contract_rejects_oos_outside_window() -> None:
    spec_v2 = SimpleNamespace(code="pit_daily_core", version=2)
    spec_v3 = SimpleNamespace(code="pit_daily_core", version=3)
    with pytest.raises(FairCompareError, match="outside"):
        assert_fair_model_run_contract(
            _make_run(run_id=1, date_from=date(2024, 1, 1), date_to=date(2024, 6, 30)),
            _make_run(run_id=2, date_from=date(2024, 1, 1), date_to=date(2024, 6, 30)),
            oos_start=date(2025, 1, 1),
            hyperparameters=dict(CATBOOST_HYPERPARAMETERS),
            random_seed=RANDOM_SEED,
            spec_v2=spec_v2,
            spec_v3=spec_v3,
        )


def test_research_pins_and_registry_forbidden(core_db) -> None:
    from app.modules.prediction.application.research_runner import run_experimental_v2_v3_oos
    from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
    from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG

    assert CANDIDATE_V0_LOCKED_VERSION == 2
    assert CANDIDATE_V1_LOCKED_VERSION == 2
    assert CANDIDATE_V0_CONFIG.dataset_spec_version == 2
    assert CANDIDATE_V1_RANKER_CONFIG.dataset_spec_version == 2
    with pytest.raises(ValueError, match="must not persist"):
        run_experimental_v2_v3_oos(core_db, dataset_spec_version=3, persist_registry=True)


def test_compare_reuses_existing_runs_without_activating(core_db, monkeypatch) -> None:
    """Reuse existing SUCCESS runs; exact DatasetSpec flags before==after."""
    from sqlalchemy import select

    from app.infrastructure.learning.models import DatasetRun, DatasetSpec

    seed_dataset_specs(core_db)
    before = snapshot_dataset_spec_flags(core_db)

    def boom(*_a, **_k):
        raise AssertionError("seed_dataset_specs must not run on compare")

    monkeypatch.setattr("app.modules.learning.application.seed.seed_dataset_specs", boom)
    monkeypatch.setattr("app.modules.learning.application.builder.seed_dataset_specs", boom)

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
        v2_run = DatasetRun(
            dataset_spec_id=v2_spec.id,
            date_from=date(2024, 1, 1),
            date_to=date(2024, 1, 31),
            status="SUCCESS",
        )
        v3_run = DatasetRun(
            dataset_spec_id=v3_spec.id,
            date_from=date(2024, 1, 1),
            date_to=date(2024, 1, 31),
            status="SUCCESS",
        )
        core_db.add_all([v2_run, v3_run])
        core_db.flush()
    elif v2_run.date_from != v3_run.date_from or v2_run.date_to != v3_run.date_to:
        return

    # Temporary non-default active fixture: V2 active.
    # Deactivate first (unique one-active-per-code constraint).
    for spec in core_db.scalars(select(DatasetSpec)).all():
        spec.is_active = False
    core_db.flush()
    v2_spec.is_active = True
    core_db.flush()
    before_v2 = snapshot_dataset_spec_flags(core_db)
    assert any(r["version"] == 2 and r["is_active"] for r in before_v2 if r["code"] == "pit_daily_core")

    artifact = compare_v2_v3_builds(
        core_db,
        date_from=v2_run.date_from,
        date_to=v2_run.date_to,
        v2_run_id=v2_run.id,
        v3_run_id=v3_run.id,
        rebuild=False,
    )
    after = snapshot_dataset_spec_flags(core_db)
    assert artifact["label"] == "EXPERIMENTAL_V3_RESEARCH"
    assert artifact["active_dataset_spec"]["before"] == before_v2
    assert artifact["active_dataset_spec"]["after"] == after
    assert artifact["active_dataset_spec"]["unchanged"] is True
    assert artifact["active_dataset_spec"]["active_state_unchanged"] is True
    assert after == before_v2
    assert after != before  # still V2-active, not silently reset to v1
    assert not any("wins" in x.lower() for x in artifact["interpretation"])


def test_compare_missing_spec_is_clean_error(core_db) -> None:
    with pytest.raises(CompareContractError, match="missing DatasetSpec"):
        _require_spec(core_db, 99)


def test_research_loader_allows_v2_v3_v4_not_v1(core_db) -> None:
    from app.modules.prediction.application.research_dataset_loader import (
        ALLOWED_RESEARCH_VERSIONS,
        ResearchDatasetError,
        resolve_research_dataset_run,
    )

    seed_dataset_specs(core_db)
    assert ALLOWED_RESEARCH_VERSIONS == frozenset({2, 3, 4})
    try:
        resolve_research_dataset_run(core_db, dataset_spec_version=1)
        raise AssertionError("expected ResearchDatasetError for v1")
    except ResearchDatasetError as exc:
        assert "allows versions" in str(exc)


def test_research_loader_does_not_touch_candidate_pins() -> None:
    from app.modules.learning.dataset_config import PIT_DAILY_CORE_V2_VERSION
    from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
    from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG

    assert CANDIDATE_V0_CONFIG.dataset_spec_version == PIT_DAILY_CORE_V2_VERSION
    assert CANDIDATE_V1_RANKER_CONFIG.dataset_spec_version == PIT_DAILY_CORE_V2_VERSION
    assert CANDIDATE_V0_LOCKED_VERSION == 2
    assert CANDIDATE_V1_LOCKED_VERSION == 2
    assert PIT_DAILY_CORE_ACTIVE_VERSION == 1


def test_experimental_oos_forbids_registry_persist(core_db) -> None:
    from app.modules.prediction.application.research_runner import run_experimental_v2_v3_oos

    with pytest.raises(ValueError, match="must not persist"):
        run_experimental_v2_v3_oos(
            core_db,
            dataset_spec_version=3,
            persist_registry=True,
        )
