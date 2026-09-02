"""Unit tests for ForwardReturnLabelCalculator and PIT validator."""

from __future__ import annotations

from datetime import date, timedelta

from app.modules.learning.application.contracts import (
    DatasetFeatureVectorV1,
    DatasetLabelsV1,
    DatasetLineageV1,
    DatasetQualityV1,
    DatasetSampleV1,
)
from app.modules.learning.application.hash_util import dataset_hash, sample_content_hash
from app.modules.learning.application.labels import ForwardReturnLabelCalculator, PriceObservation
from app.modules.learning.application.validator import (
    PITDatasetValidator,
    assert_manifest_separation,
)
from app.modules.learning.dataset_config import (
    FEATURE_MANIFEST_V1,
    feature_names_from_manifest,
    label_names_from_manifest,
)


def _obs(closes: list[float], start: date | None = None) -> list[PriceObservation]:
    start = start or date(2024, 1, 2)
    # Use weekdays-ish spaced by 1 calendar day but treat as ordered observations
    return [
        PriceObservation(date=start + timedelta(days=i), close=c, candle_id=i + 1) for i, c in enumerate(closes)
    ]


def test_forward_returns_exact() -> None:
    # closes: 100, 110, 121, 133.1 ...
    closes = [100.0, 110.0, 121.0, 133.1, 146.41, 161.051]
    calc = ForwardReturnLabelCalculator([1, 5])
    result = calc.calculate(_obs(closes), as_of=date(2024, 1, 2))
    assert abs(result.labels.forward_return_1d - 0.10) < 1e-12
    assert result.labels.target_date_1d == date(2024, 1, 3)
    assert result.label_valid["1d"] is True
    assert result.labels.forward_return_5d is not None
    assert abs(result.labels.forward_return_5d - (161.051 / 100.0 - 1)) < 1e-9


def test_forward_returns_all_horizons_independent_expected() -> None:
    # 21 observations: 100, 101, ..., 120. Expected computed independently of the calculator.
    closes = [100.0 + i for i in range(21)]
    calc = ForwardReturnLabelCalculator([1, 5, 10, 20])
    result = calc.calculate(_obs(closes), as_of=date(2024, 1, 2))
    assert abs(result.labels.forward_return_1d - (101.0 / 100.0 - 1.0)) < 1e-12
    assert abs(result.labels.forward_return_5d - (105.0 / 100.0 - 1.0)) < 1e-12
    assert abs(result.labels.forward_return_10d - (110.0 / 100.0 - 1.0)) < 1e-12
    assert abs(result.labels.forward_return_20d - (120.0 / 100.0 - 1.0)) < 1e-12
    assert result.labels.target_date_1d == date(2024, 1, 3)
    assert result.labels.target_date_5d == date(2024, 1, 7)
    assert result.labels.target_date_10d == date(2024, 1, 12)
    assert result.labels.target_date_20d == date(2024, 1, 22)
    assert all(result.label_valid[f"{h}d"] for h in (1, 5, 10, 20))


def test_forward_uses_observations_not_calendar() -> None:
    # Explicit observation sequence with weekend gap in calendar labels but contiguous list
    start = date(2024, 1, 2)  # Tue
    obs = [
        PriceObservation(start, 10.0, 1),
        PriceObservation(date(2024, 1, 5), 11.0, 2),  # Fri (skip Wed/Thu)
        PriceObservation(date(2024, 1, 8), 12.0, 3),  # Mon
    ]
    calc = ForwardReturnLabelCalculator([1])
    result = calc.calculate(obs, as_of=start)
    assert result.labels.target_date_1d == date(2024, 1, 5)
    assert abs(result.labels.forward_return_1d - 0.1) < 1e-12


def test_forward_5d_skips_calendar_gaps() -> None:
    obs = [
        PriceObservation(date(2024, 1, 2), 10.0, 1),
        PriceObservation(date(2024, 1, 3), 11.0, 2),
        PriceObservation(date(2024, 1, 8), 12.0, 3),
        PriceObservation(date(2024, 1, 9), 13.0, 4),
        PriceObservation(date(2024, 1, 10), 14.0, 5),
        PriceObservation(date(2024, 1, 15), 20.0, 6),
    ]
    result = ForwardReturnLabelCalculator([5]).calculate(obs, as_of=date(2024, 1, 2))
    assert result.labels.target_date_5d == date(2024, 1, 15)
    assert abs(result.labels.forward_return_5d - 1.0) < 1e-12


def test_missing_future_label() -> None:
    calc = ForwardReturnLabelCalculator([20])
    result = calc.calculate(_obs([100.0 + i for i in range(10)]), as_of=date(2024, 1, 2))
    assert result.labels.forward_return_20d is None
    assert result.label_valid["20d"] is False


def test_discontinuity_invalidates_label() -> None:
    calc = ForwardReturnLabelCalculator([5])
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 200.0]
    obs = _obs(closes)
    # Target window (t, t+5] includes 2024-01-07 (index 5)
    result = calc.calculate(obs, as_of=date(2024, 1, 2), discontinuity_dates={date(2024, 1, 7)})
    assert result.labels.forward_return_5d is None
    assert result.label_valid["5d"] is False
    assert result.label_flags.get("price_discontinuity_in_target_window_5d")


def test_manifest_feature_label_separation() -> None:
    assert_manifest_separation(FEATURE_MANIFEST_V1)
    features = set(feature_names_from_manifest(FEATURE_MANIFEST_V1))
    labels = set(label_names_from_manifest(FEATURE_MANIFEST_V1))
    assert not (features & labels)
    assert "forward_return_5d" in labels
    assert "forward_return_5d" not in features
    vec = DatasetFeatureVectorV1(values={"return_5d": 0.1})
    assert not vec.has_label_leakage()
    leak = DatasetFeatureVectorV1(values={"forward_return_5d": 0.1})
    assert leak.has_label_leakage()


def test_pit_validator_missing_or_stale_relation_is_not_failure() -> None:
    validator = PITDatasetValidator(FEATURE_MANIFEST_V1)
    sample = DatasetSampleV1(
        instrument_id=1,
        ticker="SBER",
        as_of_date=date(2024, 6, 1),
        features=DatasetFeatureVectorV1(values={"return_5d": 0.01, "rel_imoex_w60_pearson": None}),
        labels=DatasetLabelsV1(forward_return_5d=0.02, target_date_5d=date(2024, 6, 8)),
        lineage=DatasetLineageV1(
            basic_feature_date=date(2024, 6, 1),
            technical_feature_date=date(2024, 6, 1),
            technical_signal_as_of=date(2024, 6, 1),
            relation_as_of_dates={"imoex_w60": None},
        ),
        quality=DatasetQualityV1(
            feature_state_valid=True,
            technical_available=True,
            relations_available=False,
        ),
    )
    result = validator.validate_sample(sample)
    assert result.ok is True


def test_pit_validator_rejects_future_relation() -> None:
    validator = PITDatasetValidator(FEATURE_MANIFEST_V1)
    sample = DatasetSampleV1(
        instrument_id=1,
        ticker="SBER",
        as_of_date=date(2024, 6, 1),
        features=DatasetFeatureVectorV1(values={"return_5d": 0.01}),
        labels=DatasetLabelsV1(forward_return_5d=0.02, target_date_5d=date(2024, 6, 8)),
        lineage=DatasetLineageV1(
            basic_feature_date=date(2024, 6, 1),
            technical_feature_date=date(2024, 6, 1),
            technical_signal_as_of=date(2024, 6, 1),
            relation_as_of_dates={"imoex_w60": "2024-06-08"},
        ),
        quality=DatasetQualityV1(feature_state_valid=True, technical_available=True),
    )
    result = validator.validate_sample(sample)
    assert result.ok is False
    assert any("future relation" in v for v in result.violations)


def test_pit_validator_rejects_bad_target_chronology() -> None:
    validator = PITDatasetValidator(FEATURE_MANIFEST_V1)
    sample = DatasetSampleV1(
        instrument_id=1,
        ticker="SBER",
        as_of_date=date(2024, 6, 10),
        features=DatasetFeatureVectorV1(),
        labels=DatasetLabelsV1(forward_return_1d=0.01, target_date_1d=date(2024, 6, 9)),
        lineage=DatasetLineageV1(),
        quality=DatasetQualityV1(),
    )
    result = validator.validate_sample(sample)
    assert result.ok is False


def test_future_mutation_features_stable_labels_change() -> None:
    base = [100.0 + i * 0.5 for i in range(30)]
    calc = ForwardReturnLabelCalculator([5])
    as_of = date(2024, 1, 2) + timedelta(days=10)
    a = calc.calculate(_obs(base + [200.0, 210.0]), as_of=as_of)
    b = calc.calculate(_obs(base + [1.0, 2.0]), as_of=as_of)
    # Features aren't in label calc; label may change if horizon reaches mutated future
    # For as_of at index 10, forward 5 uses index 15 which is still in `base` — same
    assert a.labels.forward_return_5d == b.labels.forward_return_5d
    # as_of is index 10; forward_5d uses index 15. Mutate that observation.
    mutated = base[:15] + [999.0] + base[16:]
    a2 = calc.calculate(_obs(mutated), as_of=as_of)
    assert a2.labels.forward_return_5d != a.labels.forward_return_5d


def test_pit_validator_rejects_future_analytics_and_technical() -> None:
    validator = PITDatasetValidator(FEATURE_MANIFEST_V1)
    sample = DatasetSampleV1(
        instrument_id=1,
        ticker="SBER",
        as_of_date=date(2024, 6, 1),
        features=DatasetFeatureVectorV1(values={"return_5d": 0.01}),
        labels=DatasetLabelsV1(forward_return_1d=0.02, target_date_1d=date(2024, 6, 3)),
        lineage=DatasetLineageV1(
            basic_feature_date=date(2024, 6, 2),
            technical_feature_date=date(2024, 6, 2),
            technical_signal_as_of=date(2024, 6, 2),
        ),
        quality=DatasetQualityV1(feature_state_valid=True, technical_available=True),
    )
    result = validator.validate_sample(sample)
    assert result.ok is False
    joined = " ".join(result.violations)
    assert "future basic" in joined
    assert "future technical feature" in joined
    assert "future technical signal" in joined


def test_source_change_changes_hashes() -> None:
    common = {
        "instrument_id": 1,
        "as_of_date": "2024-01-02",
        "labels": {"forward_return_5d": 0.2},
        "lineage_identity": {"basic_feature_id": 7},
    }
    h1 = sample_content_hash(**common, features={"return_5d": 0.1})
    h2 = sample_content_hash(**common, features={"return_5d": 0.11})
    assert h1 != h2
    d1 = dataset_hash(
        dataset_spec_code="pit_daily_core",
        dataset_spec_version=1,
        date_from="2024-01-01",
        date_to="2024-02-01",
        sample_hashes=[h1],
    )
    d2 = dataset_hash(
        dataset_spec_code="pit_daily_core",
        dataset_spec_version=1,
        date_from="2024-01-01",
        date_to="2024-02-01",
        sample_hashes=[h2],
    )
    assert d1 != d2


def test_deterministic_hashes() -> None:
    h1 = sample_content_hash(
        instrument_id=1,
        as_of_date="2024-01-02",
        features={"return_5d": 0.1},
        labels={"forward_return_5d": 0.2},
        lineage_identity={"basic_feature_id": 7},
    )
    h2 = sample_content_hash(
        instrument_id=1,
        as_of_date="2024-01-02",
        features={"return_5d": 0.1},
        labels={"forward_return_5d": 0.2},
        lineage_identity={"basic_feature_id": 7},
    )
    assert h1 == h2
    d1 = dataset_hash(
        dataset_spec_code="pit_daily_core",
        dataset_spec_version=1,
        date_from="2024-01-01",
        date_to="2024-02-01",
        sample_hashes=[h1, "abc"],
    )
    d2 = dataset_hash(
        dataset_spec_code="pit_daily_core",
        dataset_spec_version=1,
        date_from="2024-01-01",
        date_to="2024-02-01",
        sample_hashes=["abc", h1],
    )
    assert d1 == d2
