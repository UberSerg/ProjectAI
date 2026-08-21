"""Rule-based portfolio policy stub — replaceable via PortfolioPolicy port."""

from __future__ import annotations

from app.domain.ports.portfolio import PortfolioPolicy, PortfolioPolicyInput, PortfolioPolicyOutput


class RuleBasedPortfolioPolicy(PortfolioPolicy):
    def decide(self, policy_input: PortfolioPolicyInput) -> PortfolioPolicyOutput:
        return PortfolioPolicyOutput(decisions=(), metadata={"impl": "rules"})
