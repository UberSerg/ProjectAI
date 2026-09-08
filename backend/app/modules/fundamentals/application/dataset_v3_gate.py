"""Dataset V3 readiness gate — measurement only, never creates a DatasetSpec.

Fundamentals alone never yield READY_FOR_BUILD.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fundamentals.application.coverage_service import FundamentalCoverageService
from app.modules.fundamentals.application.readiness import coverage
from app.modules.fundamentals.domain.types import FUNDAMENTALS_VERSION, ReadinessStatus
from app.modules.fundamentals.infrastructure.models import (
    DividendEvent,
    FinancialReport,
    fundamentals_schema_ready,
)

GATE_NOT_READY = "NOT_READY"
GATE_READY_FOR_DATASET_DESIGN = "READY_FOR_DATASET_DESIGN"
GATE_READY_FOR_BUILD = "READY_FOR_BUILD"

# Earliest plausible RAS feature start from live FNS online window (~2021 filings,
# usable as-of cluster ~2022).
CANDIDATE_START_DATE = "2022-03-01"


def build_dataset_v3_readiness_gate(session: Session) -> dict[str, Any]:
    if not fundamentals_schema_ready(session):
        return {
            "gate": GATE_NOT_READY,
            "status": ReadinessStatus.NOT_READY.value,
            "version": FUNDAMENTALS_VERSION,
            "dataset_spec_mutated": False,
            "blockers": ["fundamentals schema missing"],
            "candidate_start_date": None,
        }

    facts = coverage(session)
    cohort = FundamentalCoverageService(session).cohort_table()
    ras_reports = int(
        session.execute(
            select(func.count())
            .select_from(FinancialReport)
            .where(FinancialReport.reporting_standard == "RAS")
        ).scalar_one()
    )
    dividends = int(
        session.execute(select(func.count()).select_from(DividendEvent)).scalar_one()
    )

    blockers: list[str] = []
    design_notes: list[str] = []

    if ras_reports == 0:
        blockers.append("no RAS financial_reports ingested")
    else:
        design_notes.append(
            f"RAS reports present ({ras_reports}); industrial FNS features designable"
        )

    industrial_with = int(cohort.get("industrial_with_reports") or 0)
    if industrial_with == 0:
        blockers.append("no industrial issuers with FNS reports in research cohort")

    if dividends == 0:
        blockers.append(
            "no dividend_events — gross total-return labels blocked "
            "(e-disclosure spike PARTIAL_RESEARCH_ONLY)"
        )

    unmapped = int(cohort.get("unmapped") or 0)
    if unmapped > 0:
        design_notes.append(
            f"{unmapped} cohort names UNMAPPED/unsupported for FNS (incl. ROSN/NVTK/GMKN/PLZL gaps)"
        )

    design_notes.append(
        "Online FNS depth ~2021–2025; deep history 2014+ not available on this feed"
    )
    design_notes.append("Banks/FI remain NOT_SUPPORTED_BY_FNS_RAS_V1")
    design_notes.append("Fundamentals alone ≠ Dataset V3 READY_FOR_BUILD")

    # Gate logic: build requires reports + dividends + acceptable industrial coverage.
    if ras_reports > 0 and dividends > 0 and industrial_with >= 5:
        gate = GATE_READY_FOR_BUILD
    elif ras_reports > 0 and industrial_with >= 1:
        gate = GATE_READY_FOR_DATASET_DESIGN
    else:
        gate = GATE_NOT_READY

    # Hard rule from the mega-task: fundamentals alone never READY_FOR_BUILD.
    if dividends == 0 and gate == GATE_READY_FOR_BUILD:
        gate = GATE_READY_FOR_DATASET_DESIGN

    return {
        "gate": gate,
        "status": gate,
        "version": FUNDAMENTALS_VERSION,
        "dataset_spec_mutated": False,
        "dataset_created": False,
        "coverage": facts,
        "research_cohort": {
            "industrial_with_reports": industrial_with,
            "industrial_mapped": cohort.get("industrial_mapped"),
            "bank_unsupported": cohort.get("bank_unsupported"),
            "unmapped": unmapped,
        },
        "ras_reports": ras_reports,
        "dividend_events": dividends,
        "blockers": blockers,
        "design_notes": design_notes,
        "candidate_start_date": CANDIDATE_START_DATE if ras_reports > 0 else None,
        "candidate_start_evidence": (
            "First cluster of FNS actualBfoDate for probed industrials ~2022-03; "
            "online window starts ~2021 fiscal year filings."
        ),
        "total_return_labels": "NOT_READY" if dividends == 0 else "CONDITIONAL",
        "human_summary": (
            "Dataset V3: design может обсуждаться после industrial RAS ingest; "
            "READY_FOR_BUILD требует дивидендный PIT-фид и не открывается fundamentals alone."
        ),
        "note": "Gate only. No DatasetSpec / train / Shadow / Candidate changes.",
    }
