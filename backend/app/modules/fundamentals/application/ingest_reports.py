"""Financial report ingestion adapter.

No accepted provider exists (see ``audit.SOURCE_FINDINGS``), so the default path records
a DEFERRED ingestion run with an explicit reason and writes nothing. When a provider is
injected, a report is persisted only if it carries a provable ``known_at``; otherwise the
row is rejected with MISSING_KNOWN_AT rather than backdated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fundamentals.application.runs import finish_run, start_run
from app.modules.fundamentals.config import PROVIDER_REPORTS
from app.modules.fundamentals.domain.types import (
    METRIC_CODES,
    DeferralReason,
    FactRef,
    IngestionStatus,
    NormalizationStatus,
    ReportRef,
)
from app.modules.fundamentals.infrastructure.models import (
    FinancialFact,
    FinancialReport,
    fundamentals_schema_ready,
)
from app.modules.fundamentals.ports import FundamentalReportProvider


@dataclass
class ReportIngestResult:
    status: str = IngestionStatus.DEFERRED.value
    reason: str | None = None
    reports_received: int = 0
    reports_inserted: int = 0
    reports_skipped: int = 0
    facts_inserted: int = 0
    facts_rejected: int = 0
    rejections: list[str] = field(default_factory=list)
    run_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "run_id": self.run_id,
            "reports_received": self.reports_received,
            "reports_inserted": self.reports_inserted,
            "reports_skipped": self.reports_skipped,
            "facts_inserted": self.facts_inserted,
            "facts_rejected": self.facts_rejected,
            "rejections": self.rejections[:20],
        }


def _existing_report(session: Session, report: ReportRef) -> FinancialReport | None:
    return session.scalar(
        select(FinancialReport).where(
            FinancialReport.issuer_id == report.issuer_id,
            FinancialReport.reporting_standard == report.reporting_standard.value,
            FinancialReport.period_type == report.period_type.value,
            FinancialReport.period_end == report.period_end,
            FinancialReport.report_version == report.report_version,
            FinancialReport.source == report.source,
        )
    )


def _persist_facts(
    session: Session, report_id: int, facts: list[FactRef], result: ReportIngestResult
) -> None:
    for fact in facts:
        normalized = fact.normalization_status is NormalizationStatus.NORMALIZED
        if normalized and fact.metric_code not in METRIC_CODES:
            result.facts_rejected += 1
            result.rejections.append(f"unregistered metric {fact.metric_code}")
            continue
        session.add(
            FinancialFact(
                report_id=report_id,
                metric_code=fact.metric_code,
                value=fact.value,
                currency=fact.currency,
                unit_scale=fact.unit_scale,
                source_metric_name=fact.source_metric_name or "",
                normalization_status=fact.normalization_status.value,
                quality_status=fact.quality_status.value,
            )
        )
        result.facts_inserted += 1
    session.flush()


def run_report_ingestion(
    session: Session,
    *,
    provider: FundamentalReportProvider | None = None,
    issuer_ids: list[int] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ReportIngestResult:
    """Idempotent. Records DEFERRED and writes nothing when no provider is configured."""
    result = ReportIngestResult()
    if not fundamentals_schema_ready(session):
        result.status = IngestionStatus.FAILED.value
        result.reason = "fundamentals schema missing; apply alembic 20260905_0018"
        return result

    requested_range = f"{date_from or '-'}..{date_to or '-'}"
    run = start_run(session, PROVIDER_REPORTS, requested_range=requested_range)
    result.run_id = run.id

    if provider is None:
        result.status = IngestionStatus.DEFERRED.value
        result.reason = DeferralReason.NO_PROVIDER_CONFIGURED.value
        finish_run(
            session,
            run,
            status=IngestionStatus.DEFERRED,
            summary={
                **result.to_dict(),
                "note": (
                    "No financial report provider injected. Configure GIR_BO_ENABLED or "
                    "EDISCLOSURE_GATEWAY credentials to ingest; nothing was written."
                ),
            },
        )
        return result

    for issuer_id in issuer_ids or []:
        for report, facts in provider.fetch_reports(
            issuer_id, date_from=date_from, date_to=date_to
        ):
            result.reports_received += 1
            # A provider may legitimately have no publication date for a report.
            if getattr(report, "known_at", None) is None:
                result.reports_skipped += 1
                result.rejections.append(
                    f"{DeferralReason.MISSING_KNOWN_AT.value}: issuer {issuer_id} "
                    f"period {report.period_end}"
                )
                continue
            if _existing_report(session, report) is not None:
                result.reports_skipped += 1
                continue
            row = FinancialReport(
                issuer_id=report.issuer_id,
                reporting_standard=report.reporting_standard.value,
                period_type=report.period_type.value,
                period_start=report.period_start,
                period_end=report.period_end,
                known_at=report.known_at,
                source=report.source,
                report_version=report.report_version,
                is_restatement=report.is_restatement,
                currency=report.currency,
                unit_scale=report.unit_scale,
                status=report.status.value,
            )
            session.add(row)
            session.flush()
            result.reports_inserted += 1
            _persist_facts(session, row.id, list(facts), result)

    if result.reports_inserted:
        status = IngestionStatus.PARTIAL if result.rejections else IngestionStatus.SUCCESS
    else:
        status = IngestionStatus.NO_CHANGES
    result.status = status.value
    finish_run(session, run, status=status, summary=result.to_dict())
    return result
