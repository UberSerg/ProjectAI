"""Backend tests for Portfolio Builder capital bounds (Candidate preview)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.investment.domain.portfolio_capital import (
    MAX_PORTFOLIO_CAPITAL,
    PortfolioCapitalError,
    validate_portfolio_capital,
)


def test_validate_portfolio_capital_accepts_100k() -> None:
    assert validate_portfolio_capital(100_000) == Decimal("100000")
    assert validate_portfolio_capital("100000") == Decimal("100000")


def test_validate_portfolio_capital_rejects_zero_and_negative() -> None:
    with pytest.raises(PortfolioCapitalError):
        validate_portfolio_capital(0)
    with pytest.raises(PortfolioCapitalError):
        validate_portfolio_capital(-1)


def test_validate_portfolio_capital_rejects_above_max() -> None:
    with pytest.raises(PortfolioCapitalError):
        validate_portfolio_capital(MAX_PORTFOLIO_CAPITAL + 1)


def test_portfolio_candidate_request_capital_rub_alias() -> None:
    from app.api.v1.investment import PortfolioCandidateRequest

    req = PortfolioCandidateRequest(capital_rub=Decimal("250000"))
    assert req.capital == Decimal("250000")


def test_portfolio_candidate_request_rejects_zero_capital() -> None:
    from pydantic import ValidationError

    from app.api.v1.investment import PortfolioCandidateRequest

    with pytest.raises(ValidationError):
        PortfolioCandidateRequest(capital=Decimal("0"))
