"""Universal observation validation: numbers, currency, provenance."""

import math
from datetime import UTC, date, datetime
from pathlib import Path

from app.modules.historical.application.validate import (
    ACCEPTED_FACT_REQUIRES_EVIDENCE,
    CONTENT_HASH_EMPTY,
    ISSUER_FACT_REQUIRES_IDENTITY,
    MONETARY_METRIC_MISSING_CURRENCY,
    VALUE_NOT_FINITE,
    ZERO_REQUIRES_EXPLICIT_ZERO_MARK,
    validate_observation,
)
from app.modules.historical.domain.evidence import (
    FetchStatus,
    HistoricalArtifact,
    ParsedObservation,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)


def _artifact(**overrides: object) -> HistoricalArtifact:
    base: dict[str, object] = {
        "source_id": "FNS-01",
        "source_url": "https://bo.nalog.gov.ru/advanced-search/organizations",
        "external_document_id": "org:1:2023",
        "document_type": "fns_bfo",
        "content_hash": "abc123",
        "parser_version": "fns_gir_bo_v1",
        "fetch_status": FetchStatus.OK,
        "first_observed_at": datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
        "period_end": date(2023, 12, 31),
        "published_at": datetime(2024, 4, 1, 9, 0, tzinfo=UTC),
        "published_at_precision": PublishedAtPrecision.DATE_ONLY,
        "historical_availability_evidence": "fns_publication_date",
        "historical_pit_quality": PitQuality.RESEARCH_ONLY,
    }
    base.update(overrides)
    return HistoricalArtifact(**base)  # type: ignore[arg-type]


def _observation(**overrides: object) -> ParsedObservation:
    base: dict[str, object] = {
        "metric_id": "ras.REVENUE",
        "source_id": "FNS-01",
        "content_hash": "abc123",
        "normalization_version": "fns_ras_v1",
        "quality_status": RecordQuality.ACCEPTED,
        "value": 100.0,
        "unit": "THOUSANDS",
        "currency": "RUB",
        "period": "2023",
        "period_end": date(2023, 12, 31),
        "reporting_standard": "RAS",
        "issuer_identity": {"inn": "7700000001"},
        "evidence": "line-2110",
        "limitations": (),
        "extra": {},
    }
    base.update(overrides)
    return ParsedObservation(**base)  # type: ignore[arg-type]


def test_clean_fact_is_accepted_without_touching_inputs() -> None:
    artifact = _artifact()
    observation = _observation(extra={"origin": "statement"})
    result = validate_observation(artifact, observation)

    assert result is not observation
    assert result.quality_status == RecordQuality.ACCEPTED
    assert result.value == 100.0
    assert result.limitations == ()
    assert result.currency == "RUB"
    assert result.extra == {"origin": "statement"}
    assert result.extra is not observation.extra
    assert result.issuer_identity == {"inn": "7700000001"}
    assert result.issuer_identity is not observation.issuer_identity
    assert observation.quality_status == RecordQuality.ACCEPTED
    assert observation.limitations == ()
    assert artifact.historical_pit_quality == PitQuality.RESEARCH_ONLY
    result.extra["mutated"] = True
    result.issuer_identity["extra"] = "no"
    assert "mutated" not in observation.extra
    assert "extra" not in observation.issuer_identity


def test_missing_value_stays_missing_and_is_not_a_zero() -> None:
    observation = _observation(value=None, unit="percent", currency=None)
    result = validate_observation(_artifact(), observation)

    assert result.value is None
    assert result.value != 0
    assert observation.value is None
    assert ZERO_REQUIRES_EXPLICIT_ZERO_MARK not in result.limitations
    assert "explicit_zero" not in result.limitations
    assert result.quality_status == RecordQuality.ACCEPTED


def test_non_finite_values_are_quarantined_and_not_replaced() -> None:
    for raw in (float("nan"), float("inf"), float("-inf"), "not-a-number"):
        observation = _observation(value=raw)
        result = validate_observation(_artifact(), observation)
        assert result.quality_status == RecordQuality.QUARANTINE
        assert VALUE_NOT_FINITE in result.limitations
        assert result.value is raw
        assert result.value != 0
        assert observation.value is raw
        if isinstance(raw, float) and math.isnan(raw):
            assert isinstance(result.value, float) and math.isnan(result.value)


def test_accepted_fact_without_evidence_is_quarantined() -> None:
    for evidence in (None, ""):
        observation = _observation(evidence=evidence, quality_status=RecordQuality.UNRESOLVED)
        result = validate_observation(_artifact(), observation)
        assert result.quality_status == RecordQuality.QUARANTINE
        assert ACCEPTED_FACT_REQUIRES_EVIDENCE in result.limitations
        assert observation.evidence == evidence
        assert observation.quality_status == RecordQuality.UNRESOLVED


def test_zero_without_explicit_mark_is_quarantined_and_not_relabelled() -> None:
    observation = _observation(value=0.0)
    result = validate_observation(_artifact(), observation)

    assert result.quality_status == RecordQuality.QUARANTINE
    assert result.value == 0.0
    assert ZERO_REQUIRES_EXPLICIT_ZERO_MARK in result.limitations
    assert "explicit_zero" not in result.limitations
    assert observation.limitations == ()


def test_explicit_zero_is_accepted() -> None:
    observation = _observation(value=0, limitations=("explicit_zero",))
    result = validate_observation(_artifact(), observation)

    assert result.quality_status == RecordQuality.ACCEPTED
    assert result.value == 0
    assert result.limitations == ("explicit_zero",)
    assert ZERO_REQUIRES_EXPLICIT_ZERO_MARK not in result.limitations


def test_monetary_metric_without_currency_is_quarantined() -> None:
    cases = ("THOUSANDS", "thousand_rub", "RUB", "per_share", "rub_per_unit", "USD")
    for unit in cases:
        observation = _observation(unit=unit, currency=None)
        result = validate_observation(_artifact(), observation)
        assert result.quality_status == RecordQuality.QUARANTINE
        assert MONETARY_METRIC_MISSING_CURRENCY in result.limitations
        assert result.currency is None

    for blank in ("", "  ", "UNKNOWN", "unknown"):
        observation = _observation(unit="thousand_rub", currency=blank)
        result = validate_observation(_artifact(), observation)
        assert MONETARY_METRIC_MISSING_CURRENCY in result.limitations
        assert result.quality_status == RecordQuality.QUARANTINE


def test_dimensionless_metric_may_omit_currency() -> None:
    observation = _observation(metric_id="macro.key_rate", unit="percent", currency=None, value=16.0)
    result = validate_observation(_artifact(), observation)

    assert result.quality_status == RecordQuality.ACCEPTED
    assert MONETARY_METRIC_MISSING_CURRENCY not in result.limitations
    assert result.currency is None


def test_empty_content_hash_is_quarantined() -> None:
    artifact = _artifact()
    observation = _observation(content_hash="  ")
    result = validate_observation(artifact, observation)
    assert result.quality_status == RecordQuality.QUARANTINE
    assert CONTENT_HASH_EMPTY in result.limitations
    assert result.content_hash == "  "

    observation = _observation()
    result = validate_observation(_artifact(content_hash=""), observation)
    assert CONTENT_HASH_EMPTY in result.limitations
    assert result.quality_status == RecordQuality.QUARANTINE
    assert artifact.content_hash == "abc123"


def test_chronology_errors_are_taken_from_the_artifact_method(monkeypatch) -> None:
    same_day = _artifact(
        published_at_precision=PublishedAtPrecision.TIMESTAMP,
        published_at=datetime(2023, 12, 31, 18, 30, tzinfo=UTC),
    )
    assert same_day.chronology_errors() == ()
    artifact = _artifact(
        published_at=datetime(2026, 10, 13, tzinfo=UTC),
        first_observed_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    result = validate_observation(artifact, _observation())
    assert artifact.chronology_errors() == ("first_observed_at_precedes_published_at",)
    assert result.quality_status == RecordQuality.QUARANTINE
    assert "first_observed_at_precedes_published_at" in result.limitations

    def _marker(self: HistoricalArtifact) -> tuple[str, ...]:
        return ("synthetic_chronology_marker",)

    monkeypatch.setattr(HistoricalArtifact, "chronology_errors", _marker)
    marked = validate_observation(_artifact(), _observation())
    assert marked.quality_status == RecordQuality.QUARANTINE
    assert "synthetic_chronology_marker" in marked.limitations


def test_issuer_fact_without_identity_is_quarantined() -> None:
    observation = _observation(
        metric_id="issuer.identity",
        value=None,
        unit=None,
        currency=None,
        issuer_identity={},
        evidence="fns_search",
        quality_status=RecordQuality.UNRESOLVED,
    )
    result = validate_observation(_artifact(), observation)

    assert result.quality_status == RecordQuality.QUARANTINE
    assert ISSUER_FACT_REQUIRES_IDENTITY in result.limitations
    assert result.value is None
    assert observation.issuer_identity == {}


def test_validation_does_not_mark_pit_verified() -> None:
    artifact = _artifact(
        historical_pit_quality=PitQuality.PIT_VERIFIED,
        historical_availability_evidence="cbr_date_update",
        published_at=datetime(2024, 1, 15, 12, 0, tzinfo=UTC),
        published_at_precision=PublishedAtPrecision.TIMESTAMP,
        period_end=date(2024, 1, 10),
        first_observed_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert artifact.chronology_errors() == ()
    result = validate_observation(artifact, _observation())

    assert artifact.historical_pit_quality == PitQuality.PIT_VERIFIED
    assert result.quality_status == RecordQuality.ACCEPTED
    assert "PIT_VERIFIED" not in result.limitations
    assert "PIT_VERIFIED" not in result.extra.values()


def test_several_reasons_are_recorded_together() -> None:
    artifact = _artifact(
        content_hash="",
        published_at=datetime(2026, 10, 13, tzinfo=UTC),
        first_observed_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    observation = _observation(
        value=0.0,
        evidence=None,
        currency=None,
        unit="thousand_rub",
        content_hash="",
        limitations=("pilot_slice",),
    )
    result = validate_observation(artifact, observation)

    assert result.quality_status == RecordQuality.QUARANTINE
    assert result.value == 0.0
    assert result.limitations == (
        "pilot_slice",
        ACCEPTED_FACT_REQUIRES_EVIDENCE,
        ZERO_REQUIRES_EXPLICIT_ZERO_MARK,
        MONETARY_METRIC_MISSING_CURRENCY,
        CONTENT_HASH_EMPTY,
        "first_observed_at_precedes_published_at",
    )
    assert observation.limitations == ("pilot_slice",)
    assert observation.value == 0.0
    assert artifact.content_hash == ""


def test_validator_source_does_not_reimplement_dates_or_reach_io() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "modules"
        / "historical"
        / "application"
        / "validate.py"
    )
    body = source.read_text(encoding="utf-8")
    for token in (
        "period_end_must_not_equal_publication_timestamp",
        "first_observed_at_precedes_published_at",
        "pit_verified_requires_publication_evidence",
        "PIT_VERIFIED",
        "PitQuality",
        "sqlalchemy",
        "httpx",
        "psycopg",
        "redis",
        "requests",
        "urllib",
        "socket",
        "prospective_captures",
        "signal_outputs",
        "committee_decisions",
    ):
        assert token not in body
