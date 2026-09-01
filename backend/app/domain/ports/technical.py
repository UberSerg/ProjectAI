"""Technical analysis model port — swap Rules/CatBoost/XGBoost later."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any
from uuid import UUID

JsonScalar = str | int | float | bool | None
JsonObject = Mapping[str, JsonScalar]


class SignalDirection(StrEnum):
    """Coarse technical state — not a trading recommendation."""

    NEUTRAL = "neutral"
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass(slots=True, frozen=True)
class FeatureSetRef:
    """Immutable pointer to a versioned feature set."""

    code: str
    version: int
    id: UUID | None = None


@dataclass(slots=True, frozen=True)
class TechnicalFeatureVector:
    """Typed PIT feature vector for TechnicalModel (no untyped bag)."""

    # Analytics basic_daily v1
    return_1d: float | None = None
    return_5d: float | None = None
    return_20d: float | None = None
    volatility_5d: float | None = None
    volatility_20d: float | None = None
    drawdown_20d: float | None = None
    volume_change_1d: float | None = None
    volume_zscore_20d: float | None = None
    # Technical technical_daily v1
    sma20_distance: float | None = None
    ema20_distance: float | None = None
    rsi14: float | None = None
    atr14_pct: float | None = None


@dataclass(slots=True, frozen=True)
class TechnicalQualityContext:
    """Source/feature quality attached to a frozen model input."""

    is_valid: bool = True
    has_sufficient_history: bool = True
    quality_flags: Mapping[str, Any] = field(default_factory=dict)
    critical: bool = False


@dataclass(slots=True, frozen=True)
class FactorContributions:
    """Controlled factor breakdown for rules_v1 (and ML explainability later)."""

    trend: float | None = None
    momentum: float | None = None
    rsi: float | None = None
    volume: float | None = None


@dataclass(slots=True, frozen=True)
class TechnicalModelInput:
    """Frozen point-in-time input. TechnicalModel must not load features itself."""

    instrument_id: int
    ticker: str
    as_of_date: date
    basic_feature_set_ref: FeatureSetRef
    technical_feature_set_ref: FeatureSetRef
    features: TechnicalFeatureVector
    quality: TechnicalQualityContext = field(default_factory=TechnicalQualityContext)


@dataclass(slots=True, frozen=True)
class TechnicalModelOutput:
    instrument_id: int
    ticker: str
    as_of_date: date
    score: float
    confidence: float
    direction: SignalDirection
    model_code: str
    model_version: int
    basic_feature_set_ref: FeatureSetRef
    technical_feature_set_ref: FeatureSetRef
    factor_contributions: FactorContributions
    is_valid: bool = True
    quality_summary: TechnicalQualityContext = field(default_factory=TechnicalQualityContext)
    metadata: JsonObject = field(default_factory=dict)


class TechnicalModel(ABC):
    """Interface preserved across RuleBasedTechnicalModel -> CatBoostTechnicalModel."""

    @abstractmethod
    def predict(self, model_input: TechnicalModelInput) -> TechnicalModelOutput:
        raise NotImplementedError
