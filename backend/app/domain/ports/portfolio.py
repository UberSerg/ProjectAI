"""Portfolio policy port — swap RuleBased -> ContextualBandit later."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class PortfolioDecision:
    ticker: str
    action: str  # future: buy/sell/hold — not implemented yet
    weight: float
    rationale: str


class PortfolioPolicy(ABC):
    @abstractmethod
    def decide(self, context: dict[str, Any]) -> list[PortfolioDecision]:
        raise NotImplementedError
