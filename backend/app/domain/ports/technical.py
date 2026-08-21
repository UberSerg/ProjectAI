"""Technical analysis model port — swap Rules/CatBoost/XGBoost later."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

JsonScalar = str | int | float | bool | None
JsonObject = Mapping[str, JsonScalar]


class SignalDirection(StrEnum):
    """Coarse directional hint — not a trading recommendation."""

    NEUTRAL = "neutral"
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass(slots=True, frozen=True)
class TechnicalModelInput:
    ticker: str
    as_of: datetime | None = None
    features: JsonObject = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class TechnicalModelOutput:
    ticker: str
    score: float
    confidence: float
    direction: SignalDirection = SignalDirection.NEUTRAL
    metadata: JsonObject = field(default_factory=dict)


class TechnicalModel(ABC):
    """Interface preserved across RuleBasedTechnicalModel -> CatBoostTechnicalModel."""

    @abstractmethod
    def predict(self, model_input: TechnicalModelInput) -> TechnicalModelOutput:
        raise NotImplementedError
