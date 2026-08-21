"""Technical analysis model port — swap Rules/CatBoost/XGBoost later."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class TechnicalSignal:
    ticker: str
    score: float
    confidence: float
    metadata: dict[str, Any]


class TechnicalModel(ABC):
    """Interface preserved across RuleBasedTechnicalModel -> CatBoostTechnicalModel."""

    @abstractmethod
    def predict(self, features: dict[str, Any]) -> TechnicalSignal:
        raise NotImplementedError
