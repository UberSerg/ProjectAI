"""Reproducible Dataset V2 vs V3 coverage comparison (correctness, not alpha).

Fair contract: identical date_from/to, feature schema, source pins, and mechanical
labels; only universe policy differs. Research-only — does not activate DatasetSpec
and must not call seed_dataset_specs() (that helper clears/sets is_active).
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
from app.modules.learning.application.seed import snapshot_dataset_spec_flags
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


def _require_spec(session: Session, version: int) -> DatasetSpec:
    spec = session.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == PIT_DAILY_CORE_CODE,
            DatasetSpec.version == version,
        )
    )
    if spec is None:
        raise CompareContractError(
            f"missing DatasetSpec {PIT_DAILY_CORE_CODE}/v{version}; "
            "compare does not seed or activate specs"
        )
    return spec


def _assert_same_window(run_a: DatasetRun, run_b: DatasetRun, date_from: date, date_to: date) -> None:
    for run, label in ((run_a, "v2"), (run_b, "v3")):
        if run.date_from != date_from or run.date_to != date_to:
            raise CompareContractError(
                f"{label} run window {run.date_from}→{run.date_to} "
                f"!= requested {date_from}→{date_to}"
            )


def _activation_payload(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    unchanged = before == after
    return {
        "before": before,
        "after": after,
        "unchanged": unchanged,
        "active_state_unchanged": unchanged,
        "current_product_expected_active_version": PIT_DAILY_CORE_ACTIVE_VERSION,
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

    Does **not** call ``seed_dataset_specs`` (activation-mutating). Specs must already
    exist; missing V2/V3 is a clean research error. Rebuild uses the dataset builder
    with ``seed_specs=False``.
    """
    if date_to < date_from:
        raise CompareContractError("date_to must be >= date_from")

    fair = assert_fair_compare_contract()
    _require_spec(session, PIT_DAILY_CORE_V2_VERSION)
    _require_spec(session, PIT_DAILY_CORE_V3_VERSION)
    active_before = snapshot_dataset_spec_flags(session)

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
            seed_specs=False,
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
            seed_specs=False,
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
    active_after = snapshot_dataset_spec_flags(session)
    activation = _activation_payload(active_before, active_after)

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
        "active_dataset_spec": activation,
        "limitations": [
            "Comparison is dataset coverage/correctness only — not model performance or alpha.",
            "Historical universe completeness remains PARTIAL.",
            "V3 Core labels are mechanical price-return (not total return).",
            "Missingness scan may be capped for large runs.",
            "Does not change DatasetSpec is_active flags; Candidate V0/V1 pins stay on V2.",
            (
                "Remaining seed_dataset_specs callers (activation-mutating, not this path): "
                "POST /learning/datasets/build, GET /learning/datasets/overview, "
                "GET /learning/datasets/specs, PITDatasetBuilder.run_build(seed_specs=True), "
                "system diagnostics seed."
            ),
        ],
    }
    return artifact
