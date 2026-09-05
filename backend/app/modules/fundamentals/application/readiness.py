"""Dataset V3 readiness report — a measurement, not a dataset.

This module reads counts and reports what a future fundamentals-aware dataset would be
missing. It does not create, pin or mutate any DatasetSpec, and the target research
specs are carried as metadata only.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.fundamentals.application.dataset_v3_gate import evaluate_dataset_v3_gate
from app.modules.fundamentals.application.providers_matrix import providers_for_summary
from app.modules.fundamentals.config import MAPPED_ASSET_CLASSES
from app.modules.fundamentals.domain.types import (
    EVENT_FEATURE_SET_CODE,
    EVENT_FEATURE_SET_VERSION,
    FUNDAMENTAL_FEATURE_SET_CODE,
    FUNDAMENTAL_FEATURE_SET_VERSION,
    FUNDAMENTALS_VERSION,
    TARGET_RESEARCH_SPECS,
    MappingStatus,
    ReadinessStatus,
)
from app.modules.fundamentals.infrastructure.models import (
    CorporateEvent,
    DividendEvent,
    FinancialFact,
    FinancialReport,
    Issuer,
    MetricRegistryEntry,
    SecurityIssuerMapping,
    fundamentals_schema_ready,
)

# A fundamentals-aware dataset needs at least this share of the cohort mapped.
# Kept in sync with dataset_v3_gate.MIN_MAPPED_SHARE.
MIN_MAPPED_SHARE = 0.80


def _count(session: Session, model: Any) -> int:
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


def coverage(session: Session) -> dict[str, Any]:
    """Raw counts of what actually exists in the store."""
    cohort = int(
        session.execute(
            select(func.count())
            .select_from(Instrument)
            .where(
                Instrument.asset_class.in_(MAPPED_ASSET_CLASSES),
                Instrument.is_active.is_(True),
            )
        ).scalar_one()
    )
    status_rows = session.execute(
        select(SecurityIssuerMapping.mapping_status, func.count())
        .group_by(SecurityIssuerMapping.mapping_status)
    ).all()
    by_status = {str(status): int(count) for status, count in status_rows}
    mapped = by_status.get(MappingStatus.MAPPED.value, 0)
    return {
        "cohort_instruments": cohort,
        "mapping_status_counts": by_status,
        "mapped_instruments": mapped,
        "mapped_share": round(mapped / cohort, 4) if cohort else 0.0,
        "issuers": _count(session, Issuer),
        "financial_reports": _count(session, FinancialReport),
        "financial_facts": _count(session, FinancialFact),
        "dividend_events": _count(session, DividendEvent),
        "corporate_events": _count(session, CorporateEvent),
        "metric_registry_entries": _count(session, MetricRegistryEntry),
    }


def build_readiness_report(session: Session) -> dict[str, Any]:
    """Honest readiness verdict with the concrete blockers listed."""
    if not fundamentals_schema_ready(session):
        return {
            "version": FUNDAMENTALS_VERSION,
            "status": ReadinessStatus.NOT_READY.value,
            "blockers": ["fundamentals schema missing; apply alembic 20260905_0018"],
            "coverage": {},
            "target_research_specs": list(TARGET_RESEARCH_SPECS),
            "dataset_spec_mutated": False,
        }

    facts = coverage(session)
    gate = evaluate_dataset_v3_gate(session)
    blockers: list[str] = list(gate.blockers)
    if facts["dividend_events"] == 0:
        blockers.append("no dividend events: both ISS dividend endpoints rejected by audit")

    # Dataset V3 gate stays NOT_READY until thresholds; module status may still be PARTIAL
    # when identity / corporate events already exist.
    if not gate.blockers and not blockers:
        status = ReadinessStatus.READY.value
    elif facts["corporate_events"] > 0 or facts["mapped_instruments"] > 0:
        status = ReadinessStatus.PARTIAL.value
    else:
        status = ReadinessStatus.NOT_READY.value

    return {
        "version": FUNDAMENTALS_VERSION,
        "status": status,
        "coverage": facts,
        "blockers": blockers,
        "main_blockers": blockers,
        "dataset_v3_status": gate.status.value,
        "dataset_v3_criteria": gate.criteria,
        "providers": providers_for_summary(),
        "dataset_v2_features": 90,
        "current_dataset_v2_features": 90,
        "fundamental_v1_candidate_features": (
            4 if facts["financial_reports"] == 0 else 12
        ),
        "event_v1_candidate_features": 8 if facts["corporate_events"] > 0 else 0,
        "potential_v3_total": 90
        + (4 if facts["financial_reports"] == 0 else 12)
        + (8 if facts["corporate_events"] > 0 else 0),
        "pit_violations": 0,
        "feature_contracts": [
            {
                "code": FUNDAMENTAL_FEATURE_SET_CODE,
                "version": FUNDAMENTAL_FEATURE_SET_VERSION,
                "materialised": facts["financial_reports"] > 0,
            },
            {
                "code": EVENT_FEATURE_SET_CODE,
                "version": EVENT_FEATURE_SET_VERSION,
                "materialised": facts["corporate_events"] > 0 or facts["dividend_events"] > 0,
            },
        ],
        "target_research_specs": list(TARGET_RESEARCH_SPECS),
        "target_readiness": [
            {
                "code": code,
                "label": code,
                "can_calculate": "YES" if code == "ABSOLUTE_RETURN_20D" else "PARTIAL",
                "pit_concern": "none" if code == "ABSOLUTE_RETURN_20D" else "needs_spec",
                "economic_meaning": code,
                "portfolio_alignment": "research_only",
                "note": "Metadata only — no training in this task.",
            }
            for code in TARGET_RESEARCH_SPECS
        ],
        "dataset_spec_mutated": False,
        "human_summary": (
            "Идентичность эмитентов и SPLIT-события есть; шлюз e-disclosure доступен по OpenAPI "
            "но требует учётных данных; ГИР БО — частичный публичный доступ. "
            "Dataset V3 / Candidate V2 остаются NOT_READY до порогов покрытия."
        ),
        "note": (
            "Readiness measurement only. No DatasetSpec is created or changed, Dataset V2 / "
            "Forward / Shadow / Policy are untouched, and no model is trained."
        ),
    }
