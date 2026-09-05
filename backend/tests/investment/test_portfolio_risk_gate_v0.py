"""Portfolio Risk Gate V0 tests."""

from __future__ import annotations

from decimal import Decimal

from app.modules.investment.domain.portfolio_risk_gate import (
    PortfolioRiskGate,
    PortfolioRiskGateStatus,
    PositionRiskInput,
)


def test_unknown_credit_research_only() -> None:
    gate = PortfolioRiskGate(allow_unknown_credit_research=True)
    v = gate.assess_position(
        PositionRiskInput(
            symbol="CORP18",
            sleeve="FIXED_INCOME",
            target_weight=0.10,
            credit_status="UNKNOWN",
            liquidity_status="GOOD",
            data_quality="READY",
            support_status="SUPPORTED",
            investment_eligibility="RESEARCH_ONLY",
            expected_yield=0.18,
        )
    )
    assert v.status is PortfolioRiskGateStatus.RESEARCH_ONLY
    assert "credit_unknown" in v.reason_codes
    assert v.allowed_in_portfolio is True


def test_low_liquidity_blocked() -> None:
    gate = PortfolioRiskGate()
    v = gate.assess_position(
        PositionRiskInput(
            symbol="ILLIQ",
            sleeve="FIXED_INCOME",
            target_weight=0.05,
            credit_status="AVAILABLE",
            liquidity_status="LOW",
            data_quality="READY",
            support_status="SUPPORTED",
            investment_eligibility="REAL_PORTFOLIO_CANDIDATE",
        )
    )
    assert v.status is PortfolioRiskGateStatus.BLOCKED
    assert "liquidity_low" in v.reason_codes
    assert v.allowed_in_portfolio is False


def test_stale_data_warning() -> None:
    gate = PortfolioRiskGate()
    v = gate.assess_position(
        PositionRiskInput(
            symbol="STALE",
            sleeve="FIXED_INCOME",
            target_weight=0.05,
            credit_status="AVAILABLE",
            liquidity_status="GOOD",
            data_quality="READY",
            support_status="SUPPORTED",
            investment_eligibility="REAL_PORTFOLIO_CANDIDATE",
            days_since_trade=10,
        )
    )
    assert v.status is PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS
    assert "stale_market_data" in v.reason_codes


def test_concentration_blocks_single_name() -> None:
    gate = PortfolioRiskGate(max_single_position=0.15)
    v = gate.assess_position(
        PositionRiskInput(
            symbol="BIG",
            sleeve="EQUITY_ALPHA",
            target_weight=0.40,
            data_quality="READY",
            support_status="SUPPORTED",
            investment_eligibility="REAL_PORTFOLIO_CANDIDATE",
            liquidity_status="GOOD",
        )
    )
    assert v.status is PortfolioRiskGateStatus.BLOCKED
    assert "concentration_exceeds_max_single_position" in v.reason_codes


def test_blocked_instrument() -> None:
    gate = PortfolioRiskGate()
    v = gate.assess_position(
        PositionRiskInput(
            symbol="X",
            sleeve="FIXED_INCOME",
            target_weight=0.1,
            blocked=True,
            block_reason="явный запрет",
        )
    )
    assert v.status is PortfolioRiskGateStatus.BLOCKED


def test_insufficient_data() -> None:
    gate = PortfolioRiskGate()
    v = gate.assess_position(
        PositionRiskInput(
            symbol="NODATA",
            sleeve="FIXED_INCOME",
            target_weight=0.05,
            data_quality="NOT_READY",
            credit_status="AVAILABLE",
            liquidity_status="GOOD",
            support_status="SUPPORTED",
            investment_eligibility="REAL_PORTFOLIO_CANDIDATE",
        )
    )
    assert v.status is PortfolioRiskGateStatus.INSUFFICIENT_DATA


def test_portfolio_deterministic_and_buckets() -> None:
    gate = PortfolioRiskGate(max_single_position=0.15)
    positions = [
        PositionRiskInput(
            symbol="OK",
            sleeve="EQUITY_ALPHA",
            target_weight=0.10,
            data_quality="READY",
            support_status="SUPPORTED",
            investment_eligibility="REAL_PORTFOLIO_CANDIDATE",
            liquidity_status="GOOD",
        ),
        PositionRiskInput(
            symbol="CORP",
            sleeve="FIXED_INCOME",
            target_weight=0.10,
            credit_status="UNKNOWN",
            liquidity_status="GOOD",
            data_quality="READY",
            support_status="SUPPORTED",
            investment_eligibility="RESEARCH_ONLY",
            expected_yield=0.18,
        ),
        PositionRiskInput(
            symbol="CASH",
            sleeve="CASH",
            target_weight=0.80,
            data_quality="READY",
        ),
    ]
    a1 = gate.assess_portfolio(capital=Decimal("100000"), positions=positions)
    a2 = gate.assess_portfolio(capital=Decimal("100000"), positions=positions)
    assert a1.status == a2.status == PortfolioRiskGateStatus.RESEARCH_ONLY
    assert "OK" in a1.approved
    assert "CORP" in a1.research_only
    assert a1.summary_ru
    assert a1.explanations_ru


def test_high_yield_not_auto_buy() -> None:
    gate = PortfolioRiskGate()
    v = gate.assess_position(
        PositionRiskInput(
            symbol="YIELD18",
            sleeve="FIXED_INCOME",
            target_weight=0.08,
            credit_status="UNKNOWN",
            liquidity_status="UNKNOWN",
            data_quality="READY",
            support_status="SUPPORTED",
            investment_eligibility="RESEARCH_ONLY",
            expected_yield=0.18,
        )
    )
    assert v.status is not PortfolioRiskGateStatus.APPROVED
    assert "high_yield_without_risk_clearance" in v.reason_codes or "credit_unknown" in v.reason_codes
