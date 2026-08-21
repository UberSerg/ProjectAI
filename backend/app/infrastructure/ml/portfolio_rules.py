"""Rule-based portfolio policy stub — replaceable via PortfolioPolicy port."""

from __future__ import annotations

from typing import Any

from app.domain.ports.portfolio import PortfolioDecision, PortfolioPolicy


class RuleBasedPortfolioPolicy(PortfolioPolicy):
    def decide(self, context: dict[str, Any]) -> list[PortfolioDecision]:
        return []
