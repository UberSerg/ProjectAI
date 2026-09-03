"""Typed application contracts for Dataset / PIT Join V0."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(slots=True)
class DatasetLabelsV1:
    forward_return_1d: float | None = None
    forward_return_5d: float | None = None
    forward_return_10d: float | None = None
    forward_return_20d: float | None = None
    target_date_1d: date | None = None
    target_date_5d: date | None = None
    target_date_10d: date | None = None
    target_date_20d: date | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in asdict(self).items():
            out[k] = v.isoformat() if isinstance(v, date) else v
        return out


@dataclass(slots=True)
class DatasetFeatureVectorV1:
    """X(t) only — never contains forward_return_*."""

    values: dict[str, float | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, float | None]:
        return dict(self.values)

    def has_label_leakage(self) -> bool:
        return any(k.startswith("forward_return_") for k in self.values)


@dataclass(slots=True)
class DatasetLineageV1:
    basic_feature_id: int | None = None
    basic_feature_set_code: str = "basic_daily"
    basic_feature_set_version: int = 1
    basic_feature_date: date | None = None
    technical_feature_id: int | None = None
    technical_feature_set_code: str = "technical_daily"
    technical_feature_set_version: int = 1
    technical_feature_date: date | None = None
    technical_signal_id: int | None = None
    technical_model_code: str = "rules"
    technical_model_version: int = 1
    technical_model_config_hash: str | None = None
    technical_signal_as_of: date | None = None
    relation_set_code: str = "basic_relations"
    relation_set_version: int = 1
    relation_snapshot_ids: dict[str, int | None] = field(default_factory=dict)
    relation_as_of_dates: dict[str, str | None] = field(default_factory=dict)
    label_close_t_candle_id: int | None = None
    label_target_candle_ids: dict[str, int | None] = field(default_factory=dict)
    dataset_spec_code: str = "pit_daily_core"
    dataset_spec_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for key in ("basic_feature_date", "technical_feature_date", "technical_signal_as_of"):
            if d.get(key) is not None and isinstance(d[key], date):
                d[key] = d[key].isoformat()
        return d


@dataclass(slots=True)
class DatasetQualityV1:
    feature_state_valid: bool = False
    technical_available: bool = False
    # True iff at least one pinned relation context is usable for this sample.
    relations_available: bool = False
    quality_flags: dict[str, Any] = field(default_factory=dict)
    label_valid: dict[str, bool] = field(default_factory=dict)
    training_eligible: dict[str, bool] = field(default_factory=dict)
    relation_age_days: int | None = None
    relation_as_of_date: date | None = None
    pit_pass: bool = True
    pit_violations: list[str] = field(default_factory=list)

    def to_feature_quality_dict(self) -> dict[str, Any]:
        return {
            "feature_state_valid": self.feature_state_valid,
            "technical_available": self.technical_available,
            "relations_available": self.relations_available,
            "quality_flags": self.quality_flags,
            "relation_age_days": self.relation_age_days,
            "relation_as_of_date": self.relation_as_of_date.isoformat()
            if self.relation_as_of_date
            else None,
            "pit_pass": self.pit_pass,
            "pit_violations": self.pit_violations,
        }

    def to_label_quality_dict(self) -> dict[str, Any]:
        return {"label_valid": self.label_valid}

    def to_eligibility_dict(self) -> dict[str, bool]:
        return dict(self.training_eligible)


@dataclass(slots=True)
class DatasetSampleV1:
    instrument_id: int
    ticker: str
    as_of_date: date
    features: DatasetFeatureVectorV1
    labels: DatasetLabelsV1
    lineage: DatasetLineageV1
    quality: DatasetQualityV1
    metadata: dict[str, Any] = field(default_factory=dict)
