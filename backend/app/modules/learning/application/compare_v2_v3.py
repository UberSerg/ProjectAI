"""Reproducible Dataset V2 vs V3 coverage comparison (correctness, not alpha)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.modules.learning.application.builder import PITDatasetBuilder
from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_V2_VERSION,
    PIT_DAILY_CORE_V3_VERSION,
)


def compare_v2_v3_builds(
    session: Session,
    *,
    date_from: date,
    date_to: date,
    instrument_ids: list[int] | None = None,
    baseline_commit: str | None = None,
) -> dict[str, Any]:
    """Run bounded V2 and V3 builds and return a coverage comparison artifact."""
    builder = PITDatasetBuilder(session)
    v2 = builder.run_build(
        date_from=date_from,
        date_to=date_to,
        dataset_spec_code=PIT_DAILY_CORE_CODE,
        dataset_spec_version=PIT_DAILY_CORE_V2_VERSION,
        instrument_ids=instrument_ids,
    )
    v3 = builder.run_build(
        date_from=date_from,
        date_to=date_to,
        dataset_spec_code=PIT_DAILY_CORE_CODE,
        dataset_spec_version=PIT_DAILY_CORE_V3_VERSION,
        instrument_ids=instrument_ids,
    )

    from app.infrastructure.learning.models import DatasetRun

    run_v2 = session.get(DatasetRun, v2["dataset_run_id"])
    run_v3 = session.get(DatasetRun, v3["dataset_run_id"])
    univ_v2 = dict((run_v2.resolved_universe if run_v2 else None) or {})
    univ_v3 = dict((run_v3.resolved_universe if run_v3 else None) or {})
    cov_v3 = dict((run_v3.coverage_summary if run_v3 else None) or {})
    univ_diag = dict(cov_v3.get("universe") or {})

    return {
        "baseline_commit": baseline_commit,
        "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "v2": {
            "spec": f"{PIT_DAILY_CORE_CODE}/v{PIT_DAILY_CORE_V2_VERSION}",
            "universe_policy": univ_v2.get("policy"),
            "instruments": len(univ_v2.get("instrument_ids") or []),
            "samples": v2.get("samples_total"),
            "inactive_historical_names": 0,
            "pit_status": v2.get("pit_status"),
            "pit_violations": getattr(run_v2, "pit_violations", None),
            "dataset_hash": v2.get("dataset_hash"),
            "values_hash": v2.get("values_hash"),
            "run_id": v2.get("dataset_run_id"),
        },
        "v3": {
            "spec": f"{PIT_DAILY_CORE_CODE}/v{PIT_DAILY_CORE_V3_VERSION}",
            "universe_policy": univ_v3.get("policy"),
            "historical_instruments": univ_v3.get("historically_eligible_instruments"),
            "instruments": len(univ_v3.get("instrument_ids") or []),
            "samples": v3.get("samples_total"),
            "inactive_now": univ_v3.get("inactive_now"),
            "inactive_historical_names": univ_diag.get("inactive_instruments_with_samples"),
            "samples_from_inactive": univ_diag.get(
                "samples_from_currently_inactive_instruments"
            ),
            "rejected_before_eligible_from": univ_diag.get(
                "samples_rejected_before_eligible_from"
            ),
            "rejected_after_eligible_to": univ_diag.get("samples_rejected_after_eligible_to"),
            "year_coverage": cov_v3.get("by_year"),
            "boundary_quality": univ_diag.get("boundary_quality")
            or {
                "eligible_from_quality_counts": univ_v3.get("eligible_from_quality_counts"),
                "eligible_to_quality_counts": univ_v3.get("eligible_to_quality_counts"),
                "universe_quality": univ_v3.get("universe_quality"),
            },
            "pit_status": v3.get("pit_status"),
            "pit_violations": getattr(run_v3, "pit_violations", None),
            "dataset_hash": v3.get("dataset_hash"),
            "values_hash": v3.get("values_hash"),
            "run_id": v3.get("dataset_run_id"),
        },
        "limitations": [
            "Comparison is dataset coverage/correctness only — not model performance or alpha.",
            "Historical universe completeness remains PARTIAL.",
            "V3 Core labels are mechanical price-return (not total return).",
        ],
    }
