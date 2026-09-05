"""Asset Allocation Foundation V0 unit tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.investment.domain.allocation import AllocationCandidate, AssetSleeve, allocate_integer_lots
from app.modules.investment.domain.fixed_income import TransactionCostProfile
from app.modules.investment.domain.policy import (
    STATIC_100_CASH,
    STATIC_100_EQUITY,
    STATIC_100_FIXED_INCOME,
    AllocationConstraints,
    AllocationContext,
    AllocationStatus,
    CashOpportunity,
    CbrHurdleGatePolicyV0,
    EquityOpportunity,
    FixedIncomeOpportunity,
    PolicyId,
    PredictionQuality,
    get_policy,
)


def _ctx(
    *,
    excess: float | None = None,
    fi_supported_ratio: float | None = 0.5,
    fi_data_quality: str = "READY",
    credit: str = "UNKNOWN",
    cbr: float | None = 0.18,
    capital: Decimal = Decimal("100000"),
) -> AllocationContext:
    return AllocationContext(
        as_of_date=date(2026, 9, 5),
        available_capital=capital,
        cbr_hurdle_annual=cbr,
        equity=EquityOpportunity(
            expected_return=None if excess is None else (cbr or 0) + excess,
            expected_excess_return=excess,
            confidence=None,
            model_source="test",
            timestamp=date(2026, 9, 5),
            prediction_quality=PredictionQuality.UNKNOWN,
        ),
        fixed_income=FixedIncomeOpportunity(
            expected_yield=0.15,
            duration=5.0,
            credit_quality=credit,
            liquidity="UNKNOWN",
            data_quality=fi_data_quality,
            supported_ratio=fi_supported_ratio,
        ),
        cash=CashOpportunity(
            annual_rate=cbr,
            horizon_return=cbr,
            source="CBR",
            quality="DATE_ONLY",
        ),
        constraints=AllocationConstraints(),
        required_equity_premium=0.0,
    )


def test_static_policies_sum_to_one_and_non_negative() -> None:
    for policy in (STATIC_100_EQUITY, STATIC_100_FIXED_INCOME, STATIC_100_CASH):
        decision = policy.decide(_ctx())
        assert decision.equity_weight + decision.fixed_income_weight + decision.cash_weight == pytest.approx(1.0)
        assert decision.equity_weight >= 0
        assert decision.fixed_income_weight >= 0
        assert decision.cash_weight >= 0
        assert decision.status is AllocationStatus.RESEARCH_ONLY


def test_static_100_equity_deterministic() -> None:
    d1 = STATIC_100_EQUITY.decide(_ctx())
    d2 = STATIC_100_EQUITY.decide(_ctx(excess=-0.5))
    assert d1.equity_weight == 1.0
    assert d2.equity_weight == 1.0
    assert d1.policy_id == PolicyId.STATIC_100_EQUITY.value


def test_cbr_gate_reduces_equity_when_excess_insufficient() -> None:
    decision = CbrHurdleGatePolicyV0().decide(_ctx(excess=-0.02))
    assert decision.equity_weight == pytest.approx(0.0)
    assert "equity_expected_excess_below_required_premium" in decision.reason_codes
    assert decision.explanation_ru
    assert "investment_score" not in decision.explanation_ru.lower()


def test_cbr_gate_keeps_equity_when_excess_clears() -> None:
    decision = CbrHurdleGatePolicyV0().decide(_ctx(excess=0.03))
    assert decision.equity_weight > 0
    assert "equity_excess_clears_hurdle" in decision.reason_codes


def test_cbr_gate_insufficient_hurdle_data() -> None:
    decision = CbrHurdleGatePolicyV0().decide(_ctx(cbr=None, excess=0.1))
    # cash opportunity also None path — rebuild
    ctx = _ctx(cbr=None, excess=0.1)
    ctx = AllocationContext(
        as_of_date=ctx.as_of_date,
        available_capital=ctx.available_capital,
        cbr_hurdle_annual=None,
        equity=ctx.equity,
        fixed_income=ctx.fixed_income,
        cash=None,
        constraints=ctx.constraints,
    )
    decision = CbrHurdleGatePolicyV0().decide(ctx)
    assert decision.status is AllocationStatus.INSUFFICIENT_DATA
    assert decision.cash_weight == pytest.approx(1.0)


def test_missing_equity_excess_does_not_guess() -> None:
    decision = CbrHurdleGatePolicyV0().decide(_ctx(excess=None))
    assert decision.equity_weight == pytest.approx(0.0)
    assert any("insufficient_data" in c for c in decision.reason_codes)


def test_unsupported_bonds_excluded_from_fi_sleeve() -> None:
    decision = CbrHurdleGatePolicyV0().decide(_ctx(excess=-0.01, fi_supported_ratio=0.0))
    assert decision.fixed_income_weight == pytest.approx(0.0)
    assert decision.cash_weight == pytest.approx(1.0)
    assert (
        "no_supported_bonds" in decision.reason_codes
        or "fixed_income_unavailable_fallback_cash" in decision.reason_codes
    )


def test_unknown_credit_still_research_usable_when_supported() -> None:
    decision = CbrHurdleGatePolicyV0().decide(_ctx(excess=-0.01, fi_supported_ratio=0.4, credit="UNKNOWN"))
    assert decision.fixed_income_weight > 0
    assert "credit_quality_unknown_research_only" in decision.reason_codes


def test_get_policy_registry() -> None:
    assert get_policy(PolicyId.CBR_HURDLE_GATE_V0.value).policy_id == PolicyId.CBR_HURDLE_GATE_V0.value


def test_100k_integer_lots_fees_and_cash_remainder() -> None:
    result = allocate_integer_lots(
        [
            AllocationCandidate("EQ", AssetSleeve.EQUITY_ALPHA, Decimal("300"), 10, Decimal("0.3")),
            AllocationCandidate("BOND", AssetSleeve.FIXED_INCOME, Decimal("980"), 1, Decimal("0.6")),
        ],
        capital=Decimal("100000"),
        costs=TransactionCostProfile(Decimal("5")),
    )
    assert result.cash_remainder >= 0
    assert result.fees >= 0
    assert sum((p.cash_used for p in result.positions), Decimal()) + result.cash_remainder == Decimal("100000")
