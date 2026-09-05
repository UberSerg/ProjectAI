"""Feature contracts: no look-ahead, no fabricated values."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.fundamentals.application.features_event import build_event_features
from app.modules.fundamentals.application.features_fundamental import (
    LookaheadError,
    build_fundamental_features,
)
from app.modules.fundamentals.domain.types import (
    CorporateEventRef,
    CorporateEventType,
    DividendEventRef,
    DividendStatus,
    FactRef,
    FundamentalsState,
    NormalizationStatus,
    PeriodType,
    ReportingStandard,
    ReportRef,
)


def _state(*, as_of: date, known_at: date, facts: tuple[FactRef, ...] = ()) -> FundamentalsState:
    report = ReportRef(
        report_id=1,
        issuer_id=5,
        reporting_standard=ReportingStandard.IFRS,
        period_type=PeriodType.FY,
        period_end=date(2025, 12, 31),
        known_at=known_at,
    )
    return FundamentalsState(
        as_of=as_of, issuer_id=5, latest_report=report, facts=facts, visible_reports=1
    )


def test_fundamental_feature_known_at_never_exceeds_sample_date() -> None:
    row = build_fundamental_features(
        _state(as_of=date(2026, 6, 1), known_at=date(2026, 3, 20)), instrument_id=7
    )

    assert row is not None
    assert row.feature_known_at <= row.as_of
    assert row.features["days_since_latest_report"] == 73.0
    assert row.features["report_age_days"] == 152.0
    assert row.features["has_recent_report"] == 1.0


def test_stale_report_reports_zero_recency_but_stays_visible() -> None:
    row = build_fundamental_features(_state(as_of=date(2027, 1, 1), known_at=date(2026, 3, 20)))

    assert row is not None
    assert row.features["has_recent_report"] == 0.0


def test_no_report_produces_no_row_instead_of_zeros() -> None:
    empty = FundamentalsState(as_of=date(2026, 6, 1), issuer_id=5)

    assert build_fundamental_features(empty) is None


def test_only_normalized_facts_become_metric_features() -> None:
    facts = (
        FactRef(
            metric_code="NET_INCOME",
            value=1_500.0,
            normalization_status=NormalizationStatus.NORMALIZED,
        ),
        FactRef(
            metric_code="EBITDA",
            value=2_500.0,
            normalization_status=NormalizationStatus.AMBIGUOUS,
        ),
        FactRef(
            metric_code="REVENUE",
            value=None,
            normalization_status=NormalizationStatus.NORMALIZED,
        ),
    )
    row = build_fundamental_features(
        _state(as_of=date(2026, 6, 1), known_at=date(2026, 3, 20), facts=facts)
    )

    assert row is not None
    assert row.features["metric_NET_INCOME"] == 1_500.0
    assert "metric_EBITDA" not in row.features
    assert "metric_REVENUE" not in row.features


def test_future_known_at_is_rejected_as_lookahead() -> None:
    with pytest.raises(LookaheadError):
        build_fundamental_features(_state(as_of=date(2026, 3, 1), known_at=date(2026, 3, 20)))


def test_event_features_use_only_disclosed_records() -> None:
    split = CorporateEventRef(
        event_type=CorporateEventType.SPLIT,
        event_date=date(2026, 4, 10),
        known_at=date(2026, 4, 10),
        source="TEST",
        instrument_id=7,
    )
    dividend = DividendEventRef(
        instrument_id=7,
        known_at=date(2026, 4, 20),
        status=DividendStatus.RECOMMENDED,
        source="TEST",
        record_date=date(2026, 7, 10),
        amount_per_share=30.0,
    )

    row = build_event_features(
        date(2026, 5, 1), instrument_id=7, corporate_events=[split], dividend_events=[dividend]
    )
    assert row is not None
    assert row.feature_known_at <= row.as_of
    assert row.features["days_since_last_split"] == 21.0
    assert row.features["split_events_365d"] == 1.0
    assert row.features["has_known_upcoming_dividend"] == 1.0
    assert row.features["days_to_next_dividend_record_date"] == 70.0

    # One day before the dividend was disclosed, only the split is known.
    earlier = build_event_features(
        date(2026, 4, 19), instrument_id=7, corporate_events=[split], dividend_events=[dividend]
    )
    assert earlier is not None
    assert "has_known_upcoming_dividend" not in earlier.features
    assert "days_to_next_dividend_record_date" not in earlier.features


def test_event_features_absent_when_nothing_is_known() -> None:
    split = CorporateEventRef(
        event_type=CorporateEventType.SPLIT,
        event_date=date(2026, 4, 10),
        known_at=date(2026, 4, 10),
        source="TEST",
        instrument_id=7,
    )

    assert build_event_features(date(2026, 4, 1), instrument_id=7, corporate_events=[split]) is None
    assert build_event_features(date(2026, 5, 1), instrument_id=7) is None
