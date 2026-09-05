"""Portfolio policy port — swap RuleBased -> ContextualBandit later."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.ports.technical import JsonObject, TechnicalModelOutput


@dataclass(slots=True, frozen=True)
class PredictionSignal:
    """Cross-sectional prediction input for Trading Policy (not a Technical signal).

    Ranking-compatible sort key is always ``score``.
    For Candidate V0, ``predicted_return_20d`` equals the expected return and is the score.
    For Candidate V1 Ranker, ``prediction_semantic=RANKING_SCORE`` and ``prediction_score``
    holds the relative score — do not format it as a percentage return.
    """

    instrument_id: int
    ticker: str
    as_of_date: date
    predicted_return_20d: float
    fold_id: str | None = None
    sample_id: int | None = None
    metadata: JsonObject = field(default_factory=dict)
    prediction_semantic: str = "EXPECTED_RETURN"
    prediction_score: float | None = None

    @property
    def score(self) -> float:
        """Generic ranking-compatible score (policy sorts by this)."""
        if self.prediction_score is not None:
            return float(self.prediction_score)
        return float(self.predicted_return_20d)

    @property
    def is_ranking_score(self) -> bool:
        return self.prediction_semantic == "RANKING_SCORE"



@dataclass(slots=True, frozen=True)
class PortfolioPolicyInput:
    as_of: datetime | None = None
    account_id: str | None = None
    signals: Sequence[TechnicalModelOutput] = ()
    prediction_signals: Sequence[PredictionSignal] = ()
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
