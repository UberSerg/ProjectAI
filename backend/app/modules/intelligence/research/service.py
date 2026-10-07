"""Intelligence Research V1 service — coverage-first, optional focused OOS.

Does not retune V4/Canonical, does not promote Candidate, does not market Dataset V5.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from app.modules.intelligence.isolation import (
    assert_production_isolation,
    production_isolation_report,
)
from app.modules.intelligence.research.constants import (
    EXPERIMENT_NAME,
    EXPERIMENT_VERSION,
    FEATURE_PACKS,
    MODE_HISTORICAL_EVALUABLE,
)
from app.modules.intelligence.research.coverage import (
    DomainEvidence,
    PackCoverageRow,
    build_coverage_matrix,
    classify_pack,
    recommended_oos_window,
)
from app.modules.intelligence.research.experiment import IntelligenceResearchExperimentV1
from app.modules.intelligence.research.oos import run_pack_chronological_oos
from app.modules.intelligence.research.packs import (
    all_feature_packs,
    prospective_only_feature_names,
)


def build_research_plan(
    *,
    as_of: date | None = None,
    domain_overrides: dict[str, DomainEvidence] | None = None,
    date_from: date | str | None = None,
    date_to: date | str | None = None,
) -> dict[str, Any]:
    """Primary deliverable when history is thin: coverage matrix + eligibility."""
    assert_production_isolation()
    as_of_d = as_of or date.today()
    matrix = build_coverage_matrix(as_of=as_of_d, domain_overrides=domain_overrides)
    pack_rows = [PackCoverageRow(**_pack_row_kwargs(row)) for row in matrix["packs"]]
    windows = {
        row.pack: recommended_oos_window(row, as_of=as_of_d)
        for row in pack_rows
        if row.historical_eligible
    }

    # Experiment window: earliest historical pack start, else as_of (no giant fake span).
    hist_starts = [
        row.earliest_honest_known_at
        for row in pack_rows
        if row.historical_eligible and row.earliest_honest_known_at is not None
    ]
    exp_from = date_from or (min(hist_starts) if hist_starts else as_of_d)
    exp_to = date_to or as_of_d
    experiment = IntelligenceResearchExperimentV1(date_from=exp_from, date_to=exp_to)

    return {
        "schema": "IntelligenceResearchPlanV1",
        "experiment_name": EXPERIMENT_NAME,
        "experiment_version": EXPERIMENT_VERSION,
        "is_dataset_v5": False,
        "research_only": True,
        "candidate_promotion": False,
        "retunes_v4": False,
        "retunes_canonical_campaign": False,
        "experiment": experiment.to_record(),
        "coverage_matrix": matrix,
        "recommended_oos_windows": {k: v for k, v in windows.items() if v is not None},
        "prospective_only_features": prospective_only_feature_names(),
        "feature_packs": {name: spec.to_dict() for name, spec in all_feature_packs().items()},
        "production_isolation": production_isolation_report(),
        "next_step": (
            "run_focused_oos"
            if matrix["historical_evaluable_packs"]
            else "stop_at_coverage_matrix"
        ),
    }


def _pack_row_kwargs(row: dict[str, Any]) -> dict[str, Any]:
    earliest = row.get("earliest_honest_known_at")
    return {
        "pack": row["pack"],
        "evaluation_mode": row["evaluation_mode"],
        "earliest_honest_known_at": (
            date.fromisoformat(earliest) if isinstance(earliest, str) else earliest
        ),
        "historical_eligible": row["historical_eligible"],
        "prospective_only": row["prospective_only"],
        "domains": tuple(row["domains"]),
        "feature_count": row["feature_count"],
        "blockers": tuple(row.get("blockers") or ()),
        "notes": tuple(row.get("notes") or ()),
    }


def evaluate_intelligence_research(
    *,
    as_of: date | None = None,
    domain_overrides: dict[str, DomainEvidence] | None = None,
    frames_by_pack: dict[str, pd.DataFrame] | None = None,
    run_oos: bool = True,
) -> dict[str, Any]:
    """Coverage-first evaluation; optional focused OOS for eligible packs only.

    No after-result tuning: OOS uses frozen Evidence Engine helpers as-is.
    """
    plan = build_research_plan(as_of=as_of, domain_overrides=domain_overrides)
    oos_results: dict[str, Any] = {}
    skipped: dict[str, str] = {}

    if not run_oos or not frames_by_pack:
        return {
            **plan,
            "oos": oos_results,
            "oos_skipped": {
                name: "no_frame_or_oos_disabled" for name in FEATURE_PACKS
            },
        }

    matrix_packs = {row["pack"]: row for row in plan["coverage_matrix"]["packs"]}
    for pack_name, frame in frames_by_pack.items():
        row_dict = matrix_packs.get(pack_name)
        if row_dict is None:
            skipped[pack_name] = "unknown_pack"
            continue
        coverage = PackCoverageRow(**_pack_row_kwargs(row_dict))
        if coverage.evaluation_mode != MODE_HISTORICAL_EVALUABLE:
            skipped[pack_name] = coverage.evaluation_mode
            continue
        oos_results[pack_name] = run_pack_chronological_oos(
            frame,
            pack_name=pack_name,
            pack_coverage=coverage,
        )

    for name in FEATURE_PACKS:
        if name not in oos_results and name not in skipped:
            skipped[name] = "no_frame_supplied"

    return {
        **plan,
        "oos": oos_results,
        "oos_skipped": skipped,
    }


def pack_eligibility(
    pack_name: str,
    *,
    as_of: date | None = None,
    domain_overrides: dict[str, DomainEvidence] | None = None,
) -> dict[str, Any]:
    matrix = build_coverage_matrix(as_of=as_of, domain_overrides=domain_overrides)
    domains = {
        key: DomainEvidence(
            domain=key,
            earliest_honest_known_at=val.get("earliest_honest_known_at"),
            latest_known_at=val.get("latest_known_at"),
            row_count=int(val.get("row_count") or 0),
            known_at_quality=str(val.get("known_at_quality") or "UNKNOWN"),
            status=str(val.get("status") or "UNKNOWN"),
            limitations=tuple(val.get("limitations") or ()),
            evidence=dict(val.get("evidence") or {}),
        )
        for key, val in matrix["domains"].items()
    }
    row = classify_pack(pack_name, domains, as_of=as_of or date.today())
    return {
        "pack": row.to_dict(),
        "recommended_oos_window": recommended_oos_window(row, as_of=as_of),
        "is_dataset_v5": False,
    }
