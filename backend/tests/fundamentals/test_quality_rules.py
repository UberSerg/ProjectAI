"""Deterministic quality checks report problems instead of repairing them."""

from __future__ import annotations

from datetime import date

from app.modules.fundamentals.application.quality import (
    SEVERITY_ERROR,
    check_dividends,
    check_facts,
    check_mappings,
    check_reports,
    summarize,
)
from app.modules.fundamentals.domain.types import (
    DividendEventRef,
    DividendStatus,
    FactRef,
    MappingStatus,
    NormalizationStatus,
    PeriodType,
    ReportingStandard,
    ReportRef,
)


def _report(*, period_end: date, known_at: date, version: int = 1, restated: bool = False) -> ReportRef:
    return ReportRef(
        report_id=1,
        issuer_id=1,
        reporting_standard=ReportingStandard.IFRS,
        period_type=PeriodType.FY,
        period_end=period_end,
        known_at=known_at,
        report_version=version,
        is_restatement=restated,
    )


def test_report_known_before_period_end_is_an_error() -> None:
    issues = check_reports([_report(period_end=date(2025, 12, 31), known_at=date(2025, 11, 1))])

    codes = {issue.code for issue in issues}
    assert "REPORT_KNOWN_BEFORE_PERIOD_END" in codes
    assert summarize(issues)["status"] == SEVERITY_ERROR


def test_clean_report_produces_no_issues() -> None:
    issues = check_reports([_report(period_end=date(2025, 12, 31), known_at=date(2026, 3, 20))])

    assert issues == []
    assert summarize(issues)["status"] == "OK"


def test_unflagged_restatement_is_a_warning() -> None:
    issues = check_reports(
        [_report(period_end=date(2025, 12, 31), known_at=date(2026, 8, 1), version=2)]
    )

    assert {issue.code for issue in issues} == {"REPORT_VERSION_NOT_MARKED_RESTATEMENT"}
    assert summarize(issues)["status"] == "WARNING"


def test_normalized_fact_must_be_registered_and_valued() -> None:
    issues = check_facts(
        [
            FactRef(
                metric_code="MADE_UP_METRIC",
                value=1.0,
                normalization_status=NormalizationStatus.NORMALIZED,
            ),
            FactRef(
                metric_code="NET_INCOME",
                value=None,
                normalization_status=NormalizationStatus.NORMALIZED,
            ),
        ]
    )

    codes = {issue.code for issue in issues}
    assert codes == {"FACT_METRIC_NOT_IN_REGISTRY", "FACT_NORMALIZED_WITHOUT_VALUE"}


def test_ambiguous_metric_should_not_be_normalized() -> None:
    issues = check_facts(
        [
            FactRef(
                metric_code="EBITDA",
                value=100.0,
                normalization_status=NormalizationStatus.NORMALIZED,
            )
        ]
    )

    assert {issue.code for issue in issues} == {"FACT_AMBIGUOUS_METRIC_NORMALIZED"}


def test_disclosure_date_after_known_at_is_an_error() -> None:
    issues = check_dividends(
        [
            DividendEventRef(
                event_id=1,
                instrument_id=7,
                known_at=date(2026, 4, 20),
                status=DividendStatus.RECOMMENDED,
                source="TEST",
                announcement_date=date(2026, 5, 1),
                record_date=date(2026, 7, 10),
                amount_per_share=10.0,
            )
        ]
    )

    assert {issue.code for issue in issues} == {"DIVIDEND_DISCLOSURE_AFTER_KNOWN_AT"}


def test_future_record_date_alone_is_not_a_quality_problem() -> None:
    issues = check_dividends(
        [
            DividendEventRef(
                event_id=1,
                instrument_id=7,
                known_at=date(2026, 4, 20),
                status=DividendStatus.RECOMMENDED,
                source="TEST",
                announcement_date=date(2026, 4, 20),
                record_date=date(2026, 7, 10),
                amount_per_share=10.0,
            )
        ]
    )

    assert issues == []


def test_mapped_mapping_without_issuer_is_an_error() -> None:
    issues = check_mappings([(1, MappingStatus.MAPPED.value, None)])

    assert {issue.code for issue in issues} == {"MAPPING_MAPPED_WITHOUT_ISSUER"}


def test_unmapped_mapping_with_issuer_is_a_warning() -> None:
    issues = check_mappings([(2, MappingStatus.UNMAPPED.value, 55)])

    assert {issue.code for issue in issues} == {"MAPPING_UNMAPPED_WITH_ISSUER"}
