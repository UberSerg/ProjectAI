"""Reproducible Dataset V3 vs V4 coverage comparison (feature enrichment, not alpha).

Fair contract: identical date_from/to, historical universe, source pins, and
mechanical labels. Intended difference: V4 adds frozen PIT fund/event features.
Research-only — does not activate DatasetSpec and must not call seed_dataset_specs().
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetRun, DatasetSpec
from app.modules.learning.application.builder import PITDatasetBuilder
from app.modules.learning.application.research_eval import (
    assert_fair_v3_v4_compare_contract,
    compare_v3_v4_sample_sets,
    summarize_run_side,
)
from app.modules.learning.application.seed import snapshot_dataset_spec_flags
from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_ACTIVE_VERSION,
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_V3_VERSION,
    PIT_DAILY_CORE_V4_VERSION,
)


class CompareContractError(ValueError):
    """Raised when V3/V4 runs are not comparable under the fair contract."""


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
    for run, label in ((run_a, "v3"), (run_b, "v4")):
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


def compare_v3_v4_builds(
    session: Session,
    *,
    date_from: date,
    date_to: date,
    instrument_ids: list[int] | None = None,
    baseline_commit: str | None = None,
    v3_run_id: int | None = None,
    v4_run_id: int | None = None,
    rebuild: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    expected_samples: int | None = None,
) -> dict[str, Any]:
    """Run (or load) bounded V3 and V4 builds and return a coverage comparison artifact."""
    if date_to < date_from:
        raise CompareContractError("date_to must be >= date_from")

    fair = assert_fair_v3_v4_compare_contract()
    _require_spec(session, PIT_DAILY_CORE_V3_VERSION)
    _require_spec(session, PIT_DAILY_CORE_V4_VERSION)
    active_before = snapshot_dataset_spec_flags(session)

    builder = PITDatasetBuilder(session)
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

    if v4_run_id is not None:
        run_v4 = _load_run(session, v4_run_id, expected_version=PIT_DAILY_CORE_V4_VERSION)
    elif rebuild:
        v4_result = builder.run_build(
            date_from=date_from,
            date_to=date_to,
            dataset_spec_code=PIT_DAILY_CORE_CODE,
            dataset_spec_version=PIT_DAILY_CORE_V4_VERSION,
            instrument_ids=instrument_ids,
            seed_specs=False,
            progress_callback=progress_callback,
            expected_samples=expected_samples,
        )
        run_v4 = session.get(DatasetRun, v4_result["dataset_run_id"])
        if run_v4 is None:
            raise CompareContractError("V4 build did not persist a DatasetRun")
    else:
        raise CompareContractError("v4_run_id required when rebuild=False")

    _assert_same_window(run_v3, run_v4, date_from, date_to)

    v3_side = summarize_run_side(session, run_v3, side="v3")
    v4_side = summarize_run_side(session, run_v4, side="v4")
    v4_side["v4"] = (run_v4.coverage_summary or {}).get("v4")
    v4_side["return_truth"] = (run_v4.coverage_summary or {}).get("return_truth")
    sample_diff = compare_v3_v4_sample_sets(
        session, v3_run_id=run_v3.id, v4_run_id=run_v4.id
    )
    active_after = snapshot_dataset_spec_flags(session)
    activation = _activation_payload(active_before, active_after)

    interpretation = [
        fair["contract"],
        (
            f"V3 samples={v3_side.get('samples_total')}, V4 samples={v4_side.get('samples_total')}; "
            f"identity={sample_diff.get('fair_contract_status')}."
        ),
        f"V4 adds {fair['added_feature_count']} research features.",
        (
            "This artifact measures dataset coverage/correctness under a fair pin contract; "
            "it is not a model performance claim and does not say that V4 is better."
        ),
    ]
    if sample_diff.get("fair_contract_status") == "FAIR_CONTRACT_FAIL":
        interpretation.append(
            "Sample identity differs under the same universe/label inputs — "
            "treat this as FAIR_CONTRACT_FAIL, not a silent universe change."
        )

    return {
        "artifact_kind": "v3_v4_dataset_evaluation",
        "artifact_version": 1,
        "label": "EXPERIMENTAL_V4_RESEARCH",
        "baseline_commit": baseline_commit,
        "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "fair_compare": fair,
        "instrument_ids_filter": instrument_ids,
        "v3": v3_side,
        "v4": v4_side,
        "feature_manifest_delta": {
            "added": fair["added_features"],
            "added_count": fair["added_feature_count"],
        },
        "sample_diff": sample_diff,
        "interpretation": interpretation,
        "active_dataset_spec": activation,
        "limitations": [
            "Comparison is dataset coverage/correctness only — not model performance or alpha.",
            "V4 primary labels are mechanical price-return (not total return).",
            "Missingness is native NaN; unknown is not encoded as 0.",
            "Does not change DatasetSpec is_active flags; Candidate V0/V1 pins stay on V2.",
        ],
    }
