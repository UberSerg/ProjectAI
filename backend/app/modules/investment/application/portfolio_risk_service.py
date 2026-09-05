"""Application service for Portfolio Risk Gate V0."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.modules.investment.application.allocation_service import (
    build_allocation_context,
    preview_decision_lots,
    run_allocation_policy,
)
from app.modules.investment.application.credit_liquidity_service import (
    list_bond_risk_assessments,
)
from app.modules.investment.domain.policy import PolicyId
from app.modules.investment.domain.portfolio_risk_gate import (
    PortfolioRiskAssessment,
    PortfolioRiskGate,
    PortfolioRiskGateStatus,
    PositionRiskInput,
)
from app.modules.investment.domain.risk_budget import BALANCED_BUDGET, get_risk_budget


def assess_portfolio_risk_gate(
    session: Session,
    *,
    capital: Decimal = Decimal("100000"),
    policy_id: str = PolicyId.CBR_HURDLE_GATE_V0.value,
    profile_id: str = BALANCED_BUDGET.profile_id,
    equity_expected_excess_return: float | None = 0.0,
    equity_price: Decimal = Decimal("300"),
    equity_lot_size: int = 10,
    bond_price: Decimal = Decimal("980"),
    bond_lot_size: int = 1,
    cost_bps: Decimal = Decimal("5"),
) -> dict[str, Any]:
    """Build 100k portfolio candidate then run Opportunity + Risk Gate checks."""
    budget = get_risk_budget(profile_id)
    ctx = build_allocation_context(
        session,
        capital=capital,
        equity_expected_excess_return=equity_expected_excess_return,
    )
    decision = run_allocation_policy(ctx, policy_id=policy_id)
    lots = preview_decision_lots(
        decision,
        capital=capital,
        equity_price=equity_price,
        equity_lot_size=equity_lot_size,
        bond_price=bond_price,
        bond_lot_size=bond_lot_size,
        cost_bps=cost_bps,
    )

    bond_report = list_bond_risk_assessments(session)
    bond_items = bond_report.get("items") or []
    # Pick a representative FI instrument for the sleeve (research preview).
    fi_pick = next(
        (b for b in bond_items if b.get("support_status") == "SUPPORTED"),
        bond_items[0] if bond_items else None,
    )

    positions: list[PositionRiskInput] = []
    if decision.equity_weight > 0:
        eq = ctx.equity
        positions.append(
            PositionRiskInput(
                symbol="EQUITY_SLEEVE",
                sleeve="EQUITY_ALPHA",
                target_weight=decision.equity_weight,
                data_quality="READY" if eq and eq.expected_excess_return is not None else "PARTIAL",
                credit_status=None,
                liquidity_status="UNKNOWN",
                support_status="SUPPORTED",
                investment_eligibility=(
                    "RESEARCH_ONLY"
                    if not eq or (getattr(eq, "confidence_level", "UNKNOWN") == "UNKNOWN")
                    else "REAL_PORTFOLIO_CANDIDATE"
                ),
                risk_flags=tuple(getattr(eq, "limitations", ())[:3]) if eq else ("confidence_unknown",),
            )
        )

    if decision.fixed_income_weight > 0:
        if fi_pick is None:
            positions.append(
                PositionRiskInput(
                    symbol="FI_SLEEVE",
                    sleeve="FIXED_INCOME",
                    target_weight=decision.fixed_income_weight,
                    data_quality="NOT_READY",
                    credit_status="UNKNOWN",
                    liquidity_status="UNKNOWN",
                    support_status="UNSUPPORTED",
                    investment_eligibility="BLOCKED",
                    blocked=True,
                    block_reason="Нет облигаций в контуре для FI sleeve.",
                )
            )
        else:
            bond_symbol = str(fi_pick.get("symbol") or "BOND")
            positions.append(
                PositionRiskInput(
                    symbol="FI_SLEEVE",
                    sleeve="FIXED_INCOME",
                    target_weight=decision.fixed_income_weight,
                    data_quality=ctx.fixed_income.data_quality if ctx.fixed_income else "PARTIAL",
                    credit_status=str(fi_pick.get("credit_status") or "UNKNOWN"),
                    liquidity_status=str(fi_pick.get("liquidity_status") or "UNKNOWN"),
                    support_status=str(fi_pick.get("support_status") or "RESEARCH_ONLY"),
                    investment_eligibility=str(
                        fi_pick.get("investment_eligibility") or "RESEARCH_ONLY"
                    ),
                    days_since_trade=None,
                    expected_yield=fi_pick.get("yield_hint"),
                    risk_flags=tuple(
                        list(fi_pick.get("risk_flags") or ()) + [f"representative_bond:{bond_symbol}"]
                    ),
                )
            )

    if decision.cash_weight > 0:
        positions.append(
            PositionRiskInput(
                symbol="CASH",
                sleeve="CASH",
                target_weight=decision.cash_weight,
                data_quality="READY",
            )
        )

    gate = PortfolioRiskGate(
        max_single_position=budget.max_single_position,
        allow_unknown_credit_research=budget.max_credit_risk != "NONE",
    )
    assessment = gate.assess_portfolio(capital=capital, positions=positions)

    return {
        "capital": str(capital),
        "policy_id": policy_id,
        "profile_id": profile_id,
        "pipeline": "Opportunity → Risk Checks → Eligibility → Portfolio Candidate",
        "allocation": {
            "equity_weight": decision.equity_weight,
            "fixed_income_weight": decision.fixed_income_weight,
            "cash_weight": decision.cash_weight,
            "status": decision.status.value,
            "explanation_ru": decision.explanation_ru,
        },
        "lots": lots,
        "risk_assessment": _assessment_payload(assessment),
        "bond_universe_coverage": {
            "total": bond_report.get("total_bonds"),
            "credit": bond_report.get("credit_coverage"),
            "liquidity": bond_report.get("liquidity_coverage"),
            "eligibility": bond_report.get("eligibility_coverage"),
        },
        "mode": "PORTFOLIO_RISK_GATE_V0",
        "note": "Yield alone never approves. Research-only gate — no real money.",
    }


def assess_positions_only(
    positions: list[PositionRiskInput],
    *,
    capital: Decimal = Decimal("100000"),
    max_single_position: float = 0.15,
    allow_unknown_credit_research: bool = True,
) -> PortfolioRiskAssessment:
    gate = PortfolioRiskGate(
        max_single_position=max_single_position,
        allow_unknown_credit_research=allow_unknown_credit_research,
    )
    return gate.assess_portfolio(capital=capital, positions=positions)


def _assessment_payload(assessment: PortfolioRiskAssessment) -> dict[str, Any]:
    return {
        "status": assessment.status.value,
        "capital": str(assessment.capital),
        "positions": [
            {
                "symbol": p.symbol,
                "sleeve": p.sleeve,
                "status": p.status.value,
                "reason_codes": list(p.reason_codes),
                "explanations_ru": list(p.explanations_ru),
                "warnings_ru": list(p.warnings_ru),
                "allowed_in_portfolio": p.allowed_in_portfolio,
                "target_weight": p.target_weight,
            }
            for p in assessment.positions
        ],
        "approved": list(assessment.approved),
        "approved_with_warnings": list(assessment.approved_with_warnings),
        "research_only": list(assessment.research_only),
        "blocked": list(assessment.blocked),
        "insufficient_data": list(assessment.insufficient_data),
        "reason_codes": list(assessment.reason_codes),
        "explanations_ru": list(assessment.explanations_ru),
        "warnings_ru": list(assessment.warnings_ru),
        "limitations": list(assessment.limitations),
        "summary_ru": assessment.summary_ru,
        "status_is_gate": assessment.status
        in {
            PortfolioRiskGateStatus.APPROVED,
            PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS,
            PortfolioRiskGateStatus.RESEARCH_ONLY,
            PortfolioRiskGateStatus.BLOCKED,
            PortfolioRiskGateStatus.INSUFFICIENT_DATA,
        },
    }
