"""Portfolio policy port — swap RuleBased -> ContextualBandit later."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.ports.technical import JsonObject, TechnicalModelOutput


@dataclass(slots=True, frozen=True)
class PortfolioPolicyInput:
    as_of: datetime | None = None
    account_id: str | None = None
    signals: Sequence[TechnicalModelOutput] = ()
    constraints: JsonObject = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class PortfolioDecision:
    """Single policy suggestion — not a live broker order."""

    ticker: str
    target_weight: float
    rationale: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class PortfolioPolicyOutput:
    decisions: tuple[PortfolioDecision, ...] = ()
    metadata: JsonObject = field(default_factory=dict)


class PortfolioPolicy(ABC):
    @abstractmethod
    def decide(self, policy_input: PortfolioPolicyInput) -> PortfolioPolicyOutput:
        raise NotImplementedError
