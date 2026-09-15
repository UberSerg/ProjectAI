"""Shared capital bounds for Portfolio Builder / Candidate preview.

Capital rescales lot-aware construction only — it does not change prediction
or policy selection rules.
"""

from __future__ import annotations

from decimal import Decimal

# Default UI / API capital for the investor scenario.
DEFAULT_PORTFOLIO_CAPITAL = Decimal("100000")

# Prevent accidental pathological inputs (e.g. 1e18) from creating useless work.
MAX_PORTFOLIO_CAPITAL = Decimal("100000000")  # 100 млн ₽


class PortfolioCapitalError(ValueError):
    """Invalid capital for portfolio construction."""


def validate_portfolio_capital(capital: Decimal | int | str | float) -> Decimal:
    """Require capital > 0 and within the configured upper bound."""
    value = Decimal(str(capital))
    if value <= 0:
        raise PortfolioCapitalError("capital must be greater than 0")
    if value > MAX_PORTFOLIO_CAPITAL:
        raise PortfolioCapitalError(
            f"capital must be <= {MAX_PORTFOLIO_CAPITAL} RUB"
        )
    return value
