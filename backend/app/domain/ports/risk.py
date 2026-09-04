"""Risk Manager port — guardrails before Order Intent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domain.ports.portfolio import PortfolioDecision
from app.domain.ports.technical import JsonObject


@dataclass(slots=True, frozen=True)
class RiskDecision:
    """Risk-approved (possibly adjusted) target weight."""

    ticker: str
    target_weight: float
    rationale: str
    metadata: JsonObject = field(default_factory=dict)
    blocked: bool = False
    block_reason: str | None = None


@dataclass(slots=True, frozen=True)
class RiskOutput:
    decisions: tuple[RiskDecision, ...] = ()
    metadata: JsonObject = field(default_factory=dict)


class RiskManager(ABC):
    @abstractmethod
    def apply(
        self,
        decisions: Sequence[PortfolioDecision],
        *,
        constraints: dict[str, Any] | None = None,
    ) -> RiskOutput:
        raise NotImplementedError
