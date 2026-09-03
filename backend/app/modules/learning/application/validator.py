"""PIT Dataset Validator — temporal invariants; FAIL HARD on leakage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.modules.learning.application.contracts import DatasetSampleV1
from app.modules.learning.dataset_config import label_names_from_manifest


@dataclass(slots=True)
class PITValidationResult:
    ok: bool
    violations: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.ok = False
        self.violations.append(message)


class PITDatasetValidator:
    def __init__(self, feature_manifest: list[dict[str, str]]) -> None:
        self.label_names = set(label_names_from_manifest(feature_manifest))
        self.feature_role_names = {
            m["name"] for m in feature_manifest if m.get("role") == "feature"
        }

    def validate_sample(self, sample: DatasetSampleV1) -> PITValidationResult:
        result = PITValidationResult(ok=True)
        t = sample.as_of_date
        lin = sample.lineage

        if sample.features.has_label_leakage():
            result.fail("label fields present in feature vector")
        for name in sample.features.values:
            if name in self.label_names:
                result.fail(f"manifest label '{name}' found in features")

        if lin.basic_feature_date is not None and lin.basic_feature_date > t:
            result.fail(f"future basic feature date {lin.basic_feature_date} > {t}")
        if lin.technical_feature_date is not None and lin.technical_feature_date > t:
            result.fail(f"future technical feature date {lin.technical_feature_date} > {t}")
        if lin.technical_signal_as_of is not None and lin.technical_signal_as_of > t:
            result.fail(f"future technical signal as_of {lin.technical_signal_as_of} > {t}")

        for ctx, as_of_s in (lin.relation_as_of_dates or {}).items():
            if as_of_s is None:
                continue
            as_of = date.fromisoformat(as_of_s) if isinstance(as_of_s, str) else as_of_s
            if as_of > t:
                result.fail(f"future relation snapshot {ctx} as_of {as_of} > {t}")

        if sample.quality.relation_as_of_date is not None and sample.quality.relation_as_of_date > t:
            result.fail(
                f"future relation snapshot as_of {sample.quality.relation_as_of_date} > {t}"
            )

        labels = sample.labels
        for h, target in (
            (1, labels.target_date_1d),
            (5, labels.target_date_5d),
            (10, labels.target_date_10d),
            (20, labels.target_date_20d),
        ):
            if target is not None and target <= t:
                result.fail(f"label {h}d target_date {target} is not after sample as_of {t}")

        return result

    def validate_batch(self, samples: list[DatasetSampleV1]) -> PITValidationResult:
        aggregate = PITValidationResult(ok=True)
        for sample in samples:
            r = self.validate_sample(sample)
            if not r.ok:
                aggregate.ok = False
                for v in r.violations:
                    aggregate.violations.append(
                        f"instrument={sample.instrument_id} as_of={sample.as_of_date}: {v}"
                    )
        return aggregate


def assert_manifest_separation(feature_manifest: list[dict[str, str]]) -> None:
    features = {m["name"] for m in feature_manifest if m.get("role") == "feature"}
    labels = {m["name"] for m in feature_manifest if m.get("role") == "label"}
    overlap = features & labels
    if overlap:
        raise ValueError(f"feature/label overlap in manifest: {sorted(overlap)}")
    for name in labels:
        if not name.startswith("forward_return_"):
            raise ValueError(f"unexpected label name: {name}")
