"""Historical evidence contract: chronology and isolation."""

from datetime import UTC, date, datetime

import pytest

from app.modules.historical.application.isolation import assert_research_only_target
from app.modules.historical.domain.evidence import (
    FetchStatus,
    HistoricalArtifact,
    ParsedObservation,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)


def _artifact(**overrides: object) -> HistoricalArtifact:
    base = dict(
        source_id="CBR-01",
        source_url="https://www.cbr.ru/hd_base/KeyRate/",
        external_document_id="keyrate-2024-12-20",
        document_type="macro_series",
        content_hash="abc",
        parser_version="cbr_keyrate_v1",
        fetch_status=FetchStatus.OK,
        first_observed_at=datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
        period_end=date(2024, 12, 20),
        published_at=datetime(2024, 12, 20, 13, 30, tzinfo=UTC),
        published_at_precision=PublishedAtPrecision.DATE_ONLY,
        historical_pit_quality=PitQuality.PIT_PROXY,
        historical_availability_evidence="cbr_publication_date",
    )
    base.update(overrides)
    return HistoricalArtifact(**base)  # type: ignore[arg-type]


def test_period_end_is_not_a_publication_timestamp() -> None:
    artifact = _artifact(
        published_at_precision=PublishedAtPrecision.TIMESTAMP,
    )
    assert "period_end_must_not_equal_publication_timestamp" in artifact.chronology_errors()


def test_first_observed_at_cannot_precede_publication() -> None:
    artifact = _artifact(
        published_at=datetime(2026, 10, 13, tzinfo=UTC),
        first_observed_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert "first_observed_at_precedes_published_at" in artifact.chronology_errors()


def test_pit_verified_requires_evidence() -> None:
    artifact = _artifact(
        historical_pit_quality=PitQuality.PIT_VERIFIED,
        historical_availability_evidence=None,
        published_at=None,
        published_at_precision=PublishedAtPrecision.UNKNOWN,
    )
    assert "pit_verified_requires_publication_evidence" in artifact.chronology_errors()


def test_accepted_fact_needs_evidence_and_explicit_zero() -> None:
    missing = ParsedObservation(
        metric_id="macro.key_rate",
        source_id="CBR-01",
        content_hash="abc",
        normalization_version="v1",
        quality_status=RecordQuality.ACCEPTED,
        value=16.0,
    )
    assert "accepted_fact_requires_evidence" in missing.quality_errors()
    zero = ParsedObservation(
        metric_id="macro.key_rate",
        source_id="CBR-01",
        content_hash="abc",
        normalization_version="v1",
        quality_status=RecordQuality.ACCEPTED,
        value=0,
        evidence="row",
    )
    assert "zero_requires_explicit_zero_mark" in zero.quality_errors()


def test_historical_ingest_cannot_write_prospective_memory() -> None:
    with pytest.raises(PermissionError):
        assert_research_only_target("intelligence.prospective_captures")
