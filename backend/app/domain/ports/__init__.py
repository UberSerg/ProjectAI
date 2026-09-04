"""Dependency-inverted ports (interfaces)."""

from app.domain.ports.execution import ExecutionAdapter, HistoricalFill, OrderIntent
from app.domain.ports.llm import LLMMessage, LLMProvider, LLMResponse
from app.domain.ports.portfolio import (
    PortfolioDecision,
    PortfolioPolicy,
    PortfolioPolicyInput,
    PortfolioPolicyOutput,
    PredictionSignal,
)
from app.domain.ports.risk import RiskDecision, RiskManager, RiskOutput
from app.domain.ports.technical import (
    FactorContributions,
    FeatureSetRef,
    SignalDirection,
    TechnicalFeatureVector,
    TechnicalModel,
    TechnicalModelInput,
    TechnicalModelOutput,
    TechnicalQualityContext,
)

__all__ = [
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "PortfolioDecision",
    "PortfolioPolicy",
    "PortfolioPolicyInput",
    "PortfolioPolicyOutput",
    "PredictionSignal",
    "RiskDecision",
    "RiskManager",
    "RiskOutput",
    "ExecutionAdapter",
    "HistoricalFill",
    "OrderIntent",
    "FactorContributions",
    "FeatureSetRef",
    "SignalDirection",
    "TechnicalFeatureVector",
    "TechnicalModel",
    "TechnicalModelInput",
    "TechnicalModelOutput",
    "TechnicalQualityContext",
]
