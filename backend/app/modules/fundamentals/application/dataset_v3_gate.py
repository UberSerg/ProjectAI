"""Explicit Dataset V3 readiness thresholds — measurement only, no dataset mutation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.modules.fundamentals.domain.types import ReadinessStatus

# Documented criteria for a future fundamentals-aware Dataset V3.
MIN_MAPPED_SHARE = 0.80
MIN_HISTORY_YEARS = 3
MIN_CORE_METRIC_COVERAGE = 0.50
MIN_KNOWN_AT_EXACT_SHARE = 0.50

CORE_METRICS = ("REVENUE", "NET_INCOME", "TOTAL_ASSETS", "TOTAL_EQUITY", "CASH_AND_EQUIVALENTS")


@dataclass(frozen=True, slots=True)
class DatasetV3GateResult:
    status: ReadinessStatus
    blockers: tuple[str, ...]
    criteria: dict[str, Any]


def evaluate_dataset_v3_gate(session: Session) -> DatasetV3GateResult:
    from app.modules.fundamentals.application.readiness import coverage

    facts = coverage(session)
    blockers: list[str] = []

    mapped_share = float(facts.get("mapped_share") or 0.0)
    if mapped_share < MIN_MAPPED_SHARE:
        blockers.append(
            f"привязка эмитентов {mapped_share:.0%} < {MIN_MAPPED_SHARE:.0%}"
        )

    reports = int(facts.get("financial_reports") or 0)
    if reports == 0:
        blockers.append(
            "нет финансовых отчётов: e-disclosure Gateway доступен, но нужны учётные данные; "
            "ГИР БО — частичный публичный доступ без массовой подписки"
        )

    years = _estimate_report_years(session)
    if years < MIN_HISTORY_YEARS:
        blockers.append(f"история отчётности {years} лет < {MIN_HISTORY_YEARS}")

    core_share = _core_metric_coverage(session)
    if reports > 0 and core_share < MIN_CORE_METRIC_COVERAGE:
        blockers.append(
            f"покрытие ключевых метрик {core_share:.0%} < {MIN_CORE_METRIC_COVERAGE:.0%}"
        )

    known_at_quality = _known_at_quality_note(session, reports)
    if reports > 0 and "DATE_ONLY" in known_at_quality and "EXACT" not in known_at_quality:
        blockers.append(
            "качество known_at: преобладают даты без времени (ГИР БО actualBfoDate) — "
            "осторожный PIT"
        )

    if blockers:
        status = ReadinessStatus.NOT_READY
    elif facts.get("corporate_events", 0) or facts.get("mapped_instruments", 0):
        status = ReadinessStatus.PARTIAL
    else:
        status = ReadinessStatus.NOT_READY

    criteria = {
        "min_mapped_share": MIN_MAPPED_SHARE,
        "min_history_years": MIN_HISTORY_YEARS,
        "min_core_metric_coverage": MIN_CORE_METRIC_COVERAGE,
        "min_known_at_exact_share": MIN_KNOWN_AT_EXACT_SHARE,
        "core_metrics": list(CORE_METRICS),
        "observed": {
            "mapped_share": mapped_share,
            "financial_reports": reports,
            "history_years_estimate": years,
            "core_metric_coverage": core_share,
            "known_at_quality_note": known_at_quality,
        },
    }
    return DatasetV3GateResult(status=status, blockers=tuple(blockers), criteria=criteria)


def _estimate_report_years(session: Session) -> int:
    from sqlalchemy import extract, func, select

    from app.modules.fundamentals.infrastructure.models import FinancialReport

    row = session.execute(
        select(
            func.count(func.distinct(extract("year", FinancialReport.period_end)))
        ).select_from(FinancialReport)
    ).scalar_one()
    return int(row or 0)


def _core_metric_coverage(session: Session) -> float:
    from sqlalchemy import func, select

    from app.modules.fundamentals.infrastructure.models import FinancialFact, FinancialReport

    report_count = int(
        session.execute(select(func.count()).select_from(FinancialReport)).scalar_one() or 0
    )
    if report_count == 0:
        return 0.0
    covered_reports = int(
        session.execute(
            select(func.count(func.distinct(FinancialFact.report_id)))
            .where(FinancialFact.metric_code.in_(CORE_METRICS))
        ).scalar_one()
        or 0
    )
    return covered_reports / report_count


def _known_at_quality_note(session: Session, reports: int) -> str:
    if reports == 0:
        return "NONE"
    from sqlalchemy import select

    from app.modules.fundamentals.infrastructure.models import FinancialReport

    rows = session.scalars(select(FinancialReport.source).limit(100)).all()
    if any(str(s) == "EDISCLOSURE_GATEWAY" for s in rows):
        return "MIXED_EXACT_AND_DATE_ONLY"
    if any(str(s) == "GIR_BO" for s in rows):
        return "DATE_ONLY_PREDOMINANT"
    return "UNKNOWN"
