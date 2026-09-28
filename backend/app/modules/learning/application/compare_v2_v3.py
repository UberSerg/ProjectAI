"""Reproducible Dataset V2 vs V3 coverage comparison (correctness, not alpha).

Fair contract: identical date_from/to, feature schema, source pins, and mechanical
labels; only universe policy differs. Research-only — does not activate DatasetSpec.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetRun, DatasetSpec
from app.modules.learning.application.builder import PITDatasetBuilder
from app.modules.learning.application.research_eval import (
    assert_fair_compare_contract,
    compare_sample_sets,
    factual_interpretation,
    summarize_run_side,
)
from app.modules.learning.application.seed import seed_dataset_specs
from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_ACTIVE_VERSION,
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_V2_VERSION,
    PIT_DAILY_CORE_V3_VERSION,
)


class CompareContractError(ValueError):
    """Raised when V2/V3 runs are not comparable under the fair contract."""


def _load_run(session: Session, run_id: int, *, expected_version: int) -> DatasetRun:
    run = session.get(DatasetRun, run_id)
    if run is None:
        raise CompareContractError(f"DatasetRun {run_id} not found")
    spec = session.get(DatasetSpec, run.dataset_spec_id)
    if spec is None or spec.code != PIT_DAILY_CORE_CODE or spec.version != expected_version:
        raise CompareContractError(
            f"DatasetRun {run_id} is not {PIT_DAILY_CORE_CODE}/v{expected_version}"
        )
    if run.status not in ("SUCCESS", "WARNING"):
        raise CompareContractError(f"DatasetRun {run_id} status={run.status}")
    return run


def _assert_same_window(run_a: DatasetRun, run_b: DatasetRun, date_from: date, date_to: date) -> None:
    for run, label in ((run_a, "v2"), (run_b, "v3")):
        if run.date_from != date_from or run.date_to != date_to:
            raise CompareContractError(
                f"{label} run window {run.date_from}→{run.date_to} "
                f"!= requested {date_from}→{date_to}"
            )


def _active_spec_snapshot(session: Session) -> dict[str, Any]:
    active = session.scalar(select(DatasetSpec).where(DatasetSpec.is_active.is_(True)))
    return {
        "code": active.code if active else None,
        "version": active.version if active else None,
        "expected_active_version": PIT_DAILY_CORE_ACTIVE_VERSION,
        "unchanged": (active.version == PIT_DAILY_CORE_ACTIVE_VERSION) if active else False,
    }


def compare_v2_v3_builds(
    session: Session,
    *,
    date_from: date,
    date_to: date,
    instrument_ids: list[int] | None = None,
    baseline_commit: str | None = None,
    v2_run_id: int | None = None,
    v3_run_id: int | None = None,
    rebuild: bool = True,
) -> dict[str, Any]:
    """Run (or load) bounded V2 and V3 builds and return a coverage comparison artifact.

    When ``v2_run_id`` / ``v3_run_id`` are provided, those runs are reused (must match
    the requested date window and spec versions). Otherwise builds are executed when
    ``rebuild=True``.
    """
    if date_to < date_from:
        raise CompareContractError("date_to must be >= date_from")

    fair = assert_fair_compare_contract()
    seed_dataset_specs(session)
    active_before = _active_spec_snapshot(session)

    builder = PITDatasetBuilder(session)
    if v2_run_id is not None:
        run_v2 = _load_run(session, v2_run_id, expected_version=PIT_DAILY_CORE_V2_VERSION)
    elif rebuild:
        v2_result = builder.run_build(
            date_from=date_from,
            date_to=date_to,
            dataset_spec_code=PIT_DAILY_CORE_CODE,
            dataset_spec_version=PIT_DAILY_CORE_V2_VERSION,
            instrument_ids=instrument_ids,
        )
        run_v2 = session.get(DatasetRun, v2_result["dataset_run_id"])
        if run_v2 is None:
            raise CompareContractError("V2 build did not persist a DatasetRun")
    else:
        raise CompareContractError("v2_run_id required when rebuild=False")

    if v3_run_id is not None:
        run_v3 = _load_run(session, v3_run_id, expected_version=PIT_DAILY_CORE_V3_VERSION)
    elif rebuild:
        v3_result = builder.run_build(
            date_from=date_from,
            date_to=date_to,
            dataset_spec_code=PIT_DAILY_CORE_CODE,
            dataset_spec_version=PIT_DAILY_CORE_V3_VERSION,
            instrument_ids=instrument_ids,
        )
        run_v3 = session.get(DatasetRun, v3_result["dataset_run_id"])
        if run_v3 is None:
            raise CompareContractError("V3 build did not persist a DatasetRun")
    else:
        raise CompareContractError("v3_run_id required when rebuild=False")

    _assert_same_window(run_v2, run_v3, date_from, date_to)

    v2_side = summarize_run_side(session, run_v2, side="v2")
    v3_side = summarize_run_side(session, run_v3, side="v3")
    sample_diff = compare_sample_sets(
        session, v2_run_id=run_v2.id, v3_run_id=run_v3.id
    )
    active_after = _active_spec_snapshot(session)

    artifact: dict[str, Any] = {
        "artifact_kind": "v2_v3_dataset_evaluation",
        "artifact_version": 1,
        "label": "EXPERIMENTAL_V3_RESEARCH",
        "baseline_commit": baseline_commit,
        "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "fair_compare": fair,
        "instrument_ids_filter": instrument_ids,
        "v2": v2_side,
        "v3": v3_side,
        "sample_diff": sample_diff,
        "interpretation": factual_interpretation(
            v2=v2_side, v3=v3_side, sample_diff=sample_diff, fair=fair
        ),
        "active_dataset_spec": {
            "before": active_before,
            "after": active_after,
            "isolation_ok": (
                active_before.get("version") == PIT_DAILY_CORE_ACTIVE_VERSION
                and active_after.get("version") == PIT_DAILY_CORE_ACTIVE_VERSION
                and active_before.get("version") == active_after.get("version")
            ),
        },
        "limitations": [
            "Comparison is dataset coverage/correctness only — not model performance or alpha.",
            "Historical universe completeness remains PARTIAL.",
            "V3 Core labels are mechanical price-return (not total return).",
            "Missingness scan may be capped for large runs.",
            "Does not change ACTIVE DatasetSpec; Candidate V0/V1 pins stay on V2.",
        ],
    }
    return artifact
