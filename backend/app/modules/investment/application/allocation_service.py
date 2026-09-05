"""Application orchestration for Asset Allocation Foundation V0."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.investment.application.services import CbrHurdleProvider
from app.modules.investment.domain.allocation import (
    AllocationCandidate,
    AssetSleeve,
    allocate_integer_lots,
)
from app.modules.investment.domain.fixed_income import TransactionCostProfile
from app.modules.investment.domain.hurdle import horizon_return
from app.modules.investment.domain.policy import (
    BOND_SAFETY_REMINDER_RU,
    REASON_CODE_RU,
    AllocationConstraints,
    AllocationContext,
    AllocationDecision,
    AllocationResearchRun,
    CashOpportunity,
    EconomicVerdictView,
    EquityOpportunity,
    FixedIncomeOpportunity,
    LiquidityState,
    PolicyId,
    PredictionQuality,
    RiskState,
    get_policy,
)
from app.modules.investment.infrastructure.models import BondTerm


def build_allocation_context(
    session: Session,
    *,
    as_of: date | None = None,
    capital: Decimal = Decimal("100000"),
    equity_expected_return: float | None = None,
    equity_expected_excess_return: float | None = None,
    equity_model_source: str | None = None,
    required_equity_premium: float = 0.0,
    constraints: AllocationConstraints | None = None,
) -> AllocationContext:
    """Assemble AllocationContext from CBR + FI readiness; equity inputs are explicit research inputs.

    Current prediction models are treated as uncalibrated → prediction_quality=UNKNOWN
    unless a calibrated signal is later proven.
    """
    as_of = as_of or date.today()
    hurdle = CbrHurdleProvider(session).quote(as_of)
    cash = None
    cbr_annual = None
    if hurdle is not None:
        cbr_annual = hurdle.annual_rate
        cash = CashOpportunity(
            annual_rate=hurdle.annual_rate,
            horizon_return=horizon_return(hurdle.annual_rate, "1y"),
            source=hurdle.source,
            quality=hurdle.known_at_quality.value,
            limitations=("CBR key rate is a hurdle, not a guaranteed deposit yield",),
        )

    excess = equity_expected_excess_return
    if excess is None and equity_expected_return is not None and cbr_annual is not None:
        excess = equity_expected_return - cbr_annual

    equity = EquityOpportunity(
        expected_return=equity_expected_return,
        expected_excess_return=excess,
        confidence=None,
        model_source=equity_model_source or "RESEARCH_INPUT_OR_UNCALIBRATED_MODEL",
        timestamp=as_of,
        limitations=(
            "Prediction models may be uncalibrated",
            "prediction_quality=UNKNOWN until calibration is proven",
        ),
        prediction_quality=PredictionQuality.UNKNOWN,
    )

    terms_total = 0
    supported = 0
    unknown_credit = 0
    expected_yield = None
    duration = None
    try:
        terms_total = int(session.scalar(select(func.count()).select_from(BondTerm)) or 0)
        supported = int(
            session.scalar(select(func.count()).select_from(BondTerm).where(BondTerm.support_status == "SUPPORTED"))
            or 0
        )
        unknown_credit = int(
            session.scalar(
                select(func.count()).select_from(BondTerm).where(BondTerm.credit_quality_status == "UNKNOWN")
            )
            or 0
        )
        # Observed coupon_rate on a SUPPORTED term only — never invent yield.
        row = session.execute(
            select(BondTerm.coupon_rate)
            .where(
                BondTerm.support_status == "SUPPORTED",
                BondTerm.coupon_rate.is_not(None),
            )
            .limit(1)
        ).first()
        if row and row[0] is not None:
            rate = float(row[0])
            expected_yield = rate / 100.0 if rate > 1 else rate
    except Exception:  # noqa: BLE001 — schema may be absent in some test envs
        terms_total = supported = unknown_credit = 0

    supported_ratio = (supported / terms_total) if terms_total else None
    fi_limitations = [BOND_SAFETY_REMINDER_RU]
    if unknown_credit:
        fi_limitations.append(f"unknown_credit_bonds={unknown_credit}")
    if supported == 0:
        fi_limitations.append("no_SUPPORTED_bonds_in_local_db")

    data_quality = "READY" if supported > 0 else ("PARTIAL" if terms_total else "NOT_READY")
    fixed_income = FixedIncomeOpportunity(
        expected_yield=expected_yield,
        duration=float(duration) if duration is not None else None,
        credit_quality="UNKNOWN" if unknown_credit or terms_total == 0 else "OBSERVED",
        liquidity="UNKNOWN",
        data_quality=data_quality,
        supported_ratio=supported_ratio,
        limitations=tuple(fi_limitations),
    )

    return AllocationContext(
        as_of_date=as_of,
        available_capital=capital,
        cbr_hurdle_annual=cbr_annual,
        equity=equity,
        fixed_income=fixed_income,
        cash=cash,
        risk=RiskState(),
        liquidity=LiquidityState(stale_prices=False),
        constraints=constraints or AllocationConstraints(),
        required_equity_premium=required_equity_premium,
    )


def run_allocation_policy(
    context: AllocationContext,
    *,
    policy_id: str = PolicyId.CBR_HURDLE_GATE_V0.value,
) -> AllocationDecision:
    return get_policy(policy_id).decide(context)


def preview_decision_lots(
    decision: AllocationDecision,
    *,
    capital: Decimal,
    equity_price: Decimal,
    equity_lot_size: int = 1,
    bond_price: Decimal,
    bond_lot_size: int = 1,
    cost_bps: Decimal = Decimal("5"),
) -> dict[str, Any]:
    """Map sleeve weights → integer-lot preview (cash sleeve = remainder after buys)."""
    candidates: list[AllocationCandidate] = []
    if decision.equity_weight > 0:
        candidates.append(
            AllocationCandidate(
                symbol="EQUITY_SLEEVE",
                sleeve=AssetSleeve.EQUITY_ALPHA,
                price=equity_price,
                lot_size=equity_lot_size,
                target_weight=Decimal(str(decision.equity_weight)),
            )
        )
    if decision.fixed_income_weight > 0:
        candidates.append(
            AllocationCandidate(
                symbol="FI_SLEEVE",
                sleeve=AssetSleeve.FIXED_INCOME,
                price=bond_price,
                lot_size=bond_lot_size,
                target_weight=Decimal(str(decision.fixed_income_weight)),
            )
        )
    result = allocate_integer_lots(
        candidates,
        capital=capital,
        costs=TransactionCostProfile(cost_bps),
    )
    by_sleeve = {s.value: Decimal("0") for s in AssetSleeve}
    for pos in result.positions:
        by_sleeve[pos.sleeve.value] += pos.cash_used
    by_sleeve[AssetSleeve.CASH.value] = result.cash_remainder
    return {
        "lot_result": asdict(result),
        "sleeve_cash_used": {k: str(v) for k, v in by_sleeve.items()},
        "target_weights": {
            "equity": decision.equity_weight,
            "fixed_income": decision.fixed_income_weight,
            "cash": decision.cash_weight,
        },
    }


def decision_payload(decision: AllocationDecision) -> dict[str, Any]:
    return {
        "policy_id": decision.policy_id,
        "equity_weight": decision.equity_weight,
        "fixed_income_weight": decision.fixed_income_weight,
        "cash_weight": decision.cash_weight,
        "weights_pct": {
            "equity": round(decision.equity_weight * 100, 2),
            "fixed_income": round(decision.fixed_income_weight * 100, 2),
            "cash": round(decision.cash_weight * 100, 2),
        },
        "reason_codes": list(decision.reason_codes),
        "reason_codes_ru": [REASON_CODE_RU.get(c, c) for c in decision.reason_codes],
        "explanation_ru": decision.explanation_ru,
        "status": decision.status.value,
        "confidence": decision.confidence,
        "limitations": list(decision.limitations),
        "bond_safety_reminder": BOND_SAFETY_REMINDER_RU,
    }


def context_payload(context: AllocationContext) -> dict[str, Any]:
    return {
        "as_of_date": context.as_of_date.isoformat(),
        "available_capital": str(context.available_capital),
        "cbr_hurdle_annual": context.cbr_hurdle_annual,
        "required_equity_premium": context.required_equity_premium,
        "equity": asdict(context.equity) if context.equity else None,
        "fixed_income": asdict(context.fixed_income) if context.fixed_income else None,
        "cash": asdict(context.cash) if context.cash else None,
        "risk": asdict(context.risk),
        "liquidity": asdict(context.liquidity),
        "constraints": asdict(context.constraints),
        "bond_safety_reminder": BOND_SAFETY_REMINDER_RU,
    }


def list_policies() -> list[dict[str, str]]:
    return [
        {
            "id": PolicyId.STATIC_100_EQUITY.value,
            "title": "100% Equity",
            "kind": "static_benchmark",
        },
        {
            "id": PolicyId.STATIC_100_FIXED_INCOME.value,
            "title": "100% Fixed Income",
            "kind": "static_benchmark",
        },
        {
            "id": PolicyId.STATIC_100_CASH.value,
            "title": "100% Cash (CBR hurdle)",
            "kind": "static_benchmark",
        },
        {
            "id": PolicyId.CBR_HURDLE_GATE_V0.value,
            "title": "CBR Hurdle Gate V0",
            "kind": "research_gate",
        },
    ]


def create_allocation_research_run_contract(
    *,
    policy_id: str,
    as_of_from: date | None = None,
    as_of_to: date | None = None,
) -> AllocationResearchRun:
    return AllocationResearchRun(
        run_id=str(uuid4()),
        policy_id=policy_id,
        as_of_from=as_of_from,
        as_of_to=as_of_to,
        status="CONTRACT_ONLY",
    )


def economic_verdict_placeholder(
    *,
    portfolio_return: float | None = None,
    cbr_hurdle_return: float | None = None,
    imoex_return: float | None = None,
    max_drawdown: float | None = None,
) -> EconomicVerdictView:
    return EconomicVerdictView(
        portfolio_return=portfolio_return,
        cbr_hurdle_return=cbr_hurdle_return,
        imoex_return=imoex_return,
        max_drawdown=max_drawdown,
        risk_note="V0 shows explicit comparisons only — no magic investment_score.",
    )


def allocation_foundation_readiness(session: Session) -> dict[str, Any]:
    hurdle_ready = CbrHurdleProvider(session).quote(date.today()) is not None
    terms = int(session.scalar(select(func.count()).select_from(BondTerm)) or 0)
    return {
        "status": "PARTIAL",
        "checks": [
            {"code": "ALLOCATION_POLICY_READY", "status": "READY"},
            {"code": "CBR_HURDLE_READY", "status": "READY" if hurdle_ready else "NOT_READY"},
            {
                "code": "FIXED_INCOME_SLEEVE_DATA",
                "status": "READY" if terms else "INSUFFICIENT_DATA",
            },
            {"code": "EQUITY_CALIBRATION", "status": "UNKNOWN"},
            {"code": "HISTORICAL_ALLOCATION_BACKTEST", "status": "NOT_READY"},
            {"code": "REAL_MONEY", "status": "NOT_READY"},
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }
