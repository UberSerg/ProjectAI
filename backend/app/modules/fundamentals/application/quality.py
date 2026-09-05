"""Deterministic quality checks for the fundamentals store.

Every check is a pure function over domain records; ``run_quality_checks`` only loads
rows and delegates. Nothing is repaired automatically — an issue is reported, never
silently downgraded to make a dashboard green.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fundamentals.application import pit
from app.modules.fundamentals.domain.types import (
    METRIC_CODES,
    METRIC_REGISTRY_SEED,
    DividendEventRef,
    DividendStatus,
    FactRef,
    MappingStatus,
    MetricStatus,
    NormalizationStatus,
    ReportRef,
)
from app.modules.fundamentals.infrastructure.models import (
    DividendEvent,
    FinancialFact,
    FinancialReport,
    SecurityIssuerMapping,
    fundamentals_schema_ready,
)

SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"

_AMBIGUOUS_METRICS: frozenset[str] = frozenset(
    m.code for m in METRIC_REGISTRY_SEED if m.status is MetricStatus.AMBIGUOUS
)


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    severity: str
    subject: str
    message: str


def check_reports(reports: Iterable[ReportRef]) -> list[QualityIssue]:
    """A report cannot be known before its period closed, and versions cannot collide."""
    issues: list[QualityIssue] = []
    seen: dict[tuple[tuple[str, str, Any], int], ReportRef] = {}
    for report in reports:
        subject = f"report:{report.report_id}"
        if report.known_at < report.period_end:
            issues.append(
                QualityIssue(
                    "REPORT_KNOWN_BEFORE_PERIOD_END",
                    SEVERITY_ERROR,
                    subject,
                    f"known_at {report.known_at} precedes period_end {report.period_end}",
                )
            )
        key = (report.period_key, report.report_version)
        duplicate = seen.get(key)
        if duplicate is not None and duplicate.source == report.source:
            issues.append(
                QualityIssue(
                    "REPORT_VERSION_COLLISION",
                    SEVERITY_ERROR,
                    subject,
                    f"duplicate version {report.report_version} for period {report.period_end}",
                )
            )
        else:
            seen[key] = report
        if report.report_version > 1 and not report.is_restatement:
            issues.append(
                QualityIssue(
                    "REPORT_VERSION_NOT_MARKED_RESTATEMENT",
                    SEVERITY_WARNING,
                    subject,
                    f"version {report.report_version} is not flagged is_restatement",
                )
            )
    return issues


def check_facts(facts: Iterable[FactRef]) -> list[QualityIssue]:
    """NORMALIZED means "mapped to the registry with a value" — nothing weaker."""
    issues: list[QualityIssue] = []
    for fact in facts:
        subject = f"fact:{fact.report_id}:{fact.metric_code}"
        if fact.normalization_status is not NormalizationStatus.NORMALIZED:
            continue
        if fact.metric_code not in METRIC_CODES:
            issues.append(
                QualityIssue(
                    "FACT_METRIC_NOT_IN_REGISTRY",
                    SEVERITY_ERROR,
                    subject,
                    f"metric_code {fact.metric_code} is not registered",
                )
            )
        if fact.value is None:
            issues.append(
                QualityIssue(
                    "FACT_NORMALIZED_WITHOUT_VALUE",
                    SEVERITY_ERROR,
                    subject,
                    "normalization_status NORMALIZED requires a value",
                )
            )
        if fact.metric_code in _AMBIGUOUS_METRICS:
            issues.append(
                QualityIssue(
                    "FACT_AMBIGUOUS_METRIC_NORMALIZED",
                    SEVERITY_WARNING,
                    subject,
                    f"{fact.metric_code} is registered AMBIGUOUS and should stay SOURCE_ONLY",
                )
            )
    return issues


def check_dividends(events: Iterable[DividendEventRef]) -> list[QualityIssue]:
    """Disclosure dates cannot postdate the moment the disclosure became available."""
    issues: list[QualityIssue] = []
    for event in events:
        subject = f"dividend:{event.event_id}"
        for label, value in (
            ("announcement_date", event.announcement_date),
            ("board_recommendation_date", event.board_recommendation_date),
            ("shareholder_approval_date", event.shareholder_approval_date),
        ):
            if value is not None and value > event.known_at:
                issues.append(
                    QualityIssue(
                        "DIVIDEND_DISCLOSURE_AFTER_KNOWN_AT",
                        SEVERITY_ERROR,
                        subject,
                        f"{label} {value} is later than known_at {event.known_at}",
                    )
                )
        if event.record_date is None and event.status in {
            DividendStatus.APPROVED,
            DividendStatus.PAID,
        }:
            issues.append(
                QualityIssue(
                    "DIVIDEND_APPROVED_WITHOUT_RECORD_DATE",
                    SEVERITY_WARNING,
                    subject,
                    f"status {event.status} without a record date",
                )
            )
        if (
            event.amount_per_share is not None
            and event.amount_per_share <= 0
            and event.status is not DividendStatus.CANCELLED
        ):
            issues.append(
                QualityIssue(
                    "DIVIDEND_NON_POSITIVE_AMOUNT",
                    SEVERITY_WARNING,
                    subject,
                    f"amount_per_share {event.amount_per_share} is not positive",
                )
            )
    return issues


def check_mappings(
    mappings: Iterable[tuple[int, str, int | None]],
) -> list[QualityIssue]:
    """``mappings`` items are (mapping_id, mapping_status, issuer_id)."""
    issues: list[QualityIssue] = []
    for mapping_id, status, issuer_id in mappings:
        if status == MappingStatus.MAPPED.value and issuer_id is None:
            issues.append(
                QualityIssue(
                    "MAPPING_MAPPED_WITHOUT_ISSUER",
                    SEVERITY_ERROR,
                    f"mapping:{mapping_id}",
                    "mapping_status MAPPED requires an issuer_id",
                )
            )
        if status != MappingStatus.MAPPED.value and issuer_id is not None:
            issues.append(
                QualityIssue(
                    "MAPPING_UNMAPPED_WITH_ISSUER",
                    SEVERITY_WARNING,
                    f"mapping:{mapping_id}",
                    f"mapping_status {status} still points at issuer {issuer_id}",
                )
            )
    return issues


def summarize(issues: Sequence[QualityIssue]) -> dict[str, Any]:
    errors = [i for i in issues if i.severity == SEVERITY_ERROR]
    warnings = [i for i in issues if i.severity == SEVERITY_WARNING]
    if errors:
        status = SEVERITY_ERROR
    elif warnings:
        status = SEVERITY_WARNING
    else:
        status = "OK"
    return {
        "status": status,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": [asdict(issue) for issue in issues[:200]],
        "issues_truncated": len(issues) > 200,
    }


def run_quality_checks(session: Session) -> dict[str, Any]:
    """Whole-store check. Returns NOT_READY when the schema is not applied yet."""
    if not fundamentals_schema_ready(session):
        return {
            "status": "NOT_READY",
            "reason": "fundamentals schema missing; apply alembic 20260905_0018",
            "error_count": 0,
            "warning_count": 0,
            "issues": [],
        }

    reports = [pit.report_ref(row) for row in session.scalars(select(FinancialReport)).all()]
    facts = [pit.fact_ref(row) for row in session.scalars(select(FinancialFact)).all()]
    dividends = [pit.dividend_ref(row) for row in session.scalars(select(DividendEvent)).all()]
    mapping_rows = [
        (row.id, row.mapping_status, row.issuer_id)
        for row in session.scalars(select(SecurityIssuerMapping)).all()
    ]

    issues = [
        *check_reports(reports),
        *check_facts(facts),
        *check_dividends(dividends),
        *check_mappings(mapping_rows),
    ]
    payload = summarize(issues)
    payload["checked"] = {
        "reports": len(reports),
        "facts": len(facts),
        "dividend_events": len(dividends),
        "mappings": len(mapping_rows),
    }
    mapped = sum(1 for _, status, _ in mapping_rows if status == MappingStatus.MAPPED.value)
    unknown = sum(
        1
        for _, status, _ in mapping_rows
        if status in {MappingStatus.UNMAPPED.value, MappingStatus.AMBIGUOUS.value}
    )
    payload["issuer_mappings"] = mapped
    payload["unknown_mappings"] = unknown
    payload["ambiguous_facts"] = sum(
        1 for i in issues if i.code.startswith("FACT_") and i.severity == SEVERITY_WARNING
    )
    payload["reports_without_known_at"] = 0  # known_at is NOT NULL in schema
    payload["restatements"] = sum(1 for r in reports if r.is_restatement)
    payload["rejected_rows"] = payload.get("error_count") or 0
    if payload.get("error_count"):
        payload["status"] = "NOT_READY"
        payload["human_message"] = "Нельзя безопасно использовать в ML."
        payload["pit_quality"] = "NOT_READY"
    elif reports or dividends:
        payload["status"] = "GOOD" if not payload.get("warning_count") else "PARTIAL"
        payload["human_message"] = (
            "Данные пригодны для PIT-исследований."
            if payload["status"] == "GOOD"
            else "Часть истории не имеет точной даты публикации."
        )
        payload["pit_quality"] = payload["status"]
    else:
        payload["status"] = "NOT_READY"
        payload["human_message"] = (
            "Нельзя безопасно использовать в ML: нет отчётов/дивидендов с known_at "
            "(есть только identity и SPLIT-события)."
        )
        payload["pit_quality"] = "NOT_READY"
    return payload
