"""Application services for Risk & Opportunity Engine V0."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.investment.application.allocation_service import (
    build_allocation_context,
    preview_decision_lots,
)
from app.modules.investment.domain.calibration import (
    CalibrationStatus,
    EquityOpportunityCalibration,
    calibrate_equity_predictions,
)
from app.modules.investment.domain.decision_engine import (
    InvestmentDecision,
    InvestmentDecisionEngine,
    MarketContext,
)
from app.modules.investment.domain.hurdle import horizon_return
from app.modules.investment.domain.policy import (
    BOND_SAFETY_REMINDER_RU,
    EquityOpportunity,
    FixedIncomeOpportunity,
    PredictionQuality,
)
from app.modules.investment.domain.risk_budget import (
    RISK_BUDGETS,
    RiskProfileId,
    get_risk_budget,
)


def load_equity_calibration(session: Session, *, limit: int = 5000) -> EquityOpportunityCalibration:
    """Build calibration from EVALUATED EXPECTED_RETURN forward outcomes only."""
    pairs = _load_evaluated_pairs(session, limit=limit)
    return calibrate_equity_predictions(pairs)


def _load_evaluated_pairs(session: Session, *, limit: int) -> list[tuple[float, float]]:
    try:
        from app.modules.prediction.infrastructure.forward_models import ForwardPredictionBatch
        from app.modules.prediction.infrastructure.forward_outcome_models import (
            ForwardPredictionOutcome,
        )
    except Exception:  # noqa: BLE001
        return []

    try:
        rows = session.execute(
            select(
                ForwardPredictionOutcome.predicted_return_20d,
                ForwardPredictionOutcome.realized_return_20d,
            )
            .join(
                ForwardPredictionBatch,
                ForwardPredictionBatch.id == ForwardPredictionOutcome.batch_id,
            )
            .where(
                ForwardPredictionOutcome.status == "EVALUATED",
                ForwardPredictionOutcome.realized_return_20d.is_not(None),
                ForwardPredictionBatch.prediction_semantic == "EXPECTED_RETURN",
            )
            .order_by(ForwardPredictionOutcome.as_of_date.desc())
            .limit(limit)
        ).all()
    except Exception:  # noqa: BLE001 — schema/table may be empty/unmigrated in some envs
        return []

    pairs: list[tuple[float, float]] = []
    for pred, real in rows:
        if pred is None or real is None:
            continue
        pairs.append((float(pred), float(real)))
    return pairs


def build_enriched_opportunities(
    session: Session,
    *,
    as_of: date | None = None,
    capital: Decimal = Decimal("100000"),
    equity_expected_return: float | None = None,
    equity_expected_excess_return: float | None = None,
) -> dict[str, Any]:
    calibration = load_equity_calibration(session)
    ctx = build_allocation_context(
        session,
        as_of=as_of,
        capital=capital,
        equity_expected_return=equity_expected_return,
        equity_expected_excess_return=equity_expected_excess_return,
    )

    # Confidence: never fake. UNKNOWN unless research-adequate calibration AND excess provided.
    confidence: float | None = None
    pred_quality = PredictionQuality.UNKNOWN
    if (
        calibration.calibration_status is CalibrationStatus.ADEQUATE_FOR_RESEARCH
        and ctx.equity
        and ctx.equity.expected_excess_return is not None
    ):
        pred_quality = PredictionQuality.OBSERVED
        # Still not a calibrated probability — leave numeric confidence None.
        confidence = None

    equity = None
    if ctx.equity is not None:
        equity = EquityOpportunity(
            expected_return=ctx.equity.expected_return,
            expected_excess_return=ctx.equity.expected_excess_return,
            confidence=confidence,
            model_source=ctx.equity.model_source,
            timestamp=ctx.equity.timestamp,
            limitations=tuple(ctx.equity.limitations) + tuple(calibration.limitations),
            prediction_quality=pred_quality,
            calibration_status=calibration.calibration_status.value,
        )

    fi = None
    if ctx.fixed_income is not None:
        support = (
            "SUPPORTED"
            if (ctx.fixed_income.supported_ratio or 0) > 0
            else "NONE"
        )
        fi = FixedIncomeOpportunity(
            expected_yield=ctx.fixed_income.expected_yield,
            duration=ctx.fixed_income.duration,
            credit_quality=ctx.fixed_income.credit_quality,
            liquidity=ctx.fixed_income.liquidity,
            data_quality=ctx.fixed_income.data_quality,
            supported_ratio=ctx.fixed_income.supported_ratio,
            limitations=tuple(ctx.fixed_income.limitations)
            + ("Высокая доходность может отражать высокий риск.",),
            yield_source="OBSERVED_COUPON_RATE_OR_NONE",
            liquidity_status=ctx.fixed_income.liquidity,
            support_status=support,
        )

    return {
        "context": ctx,
        "equity": equity,
        "fixed_income": fi,
        "cash": ctx.cash,
        "calibration": calibration,
    }


def run_investment_decision(
    session: Session,
    *,
    profile_id: str = RiskProfileId.BALANCED_ALLOCATION_V0.value,
    capital: Decimal = Decimal("100000"),
    as_of: date | None = None,
    equity_expected_excess_return: float | None = None,
    equity_expected_return: float | None = None,
    equity_price: Decimal = Decimal("300"),
    equity_lot_size: int = 10,
    bond_price: Decimal = Decimal("980"),
    bond_lot_size: int = 1,
    cost_bps: Decimal = Decimal("5"),
    volatility: float | None = None,
    drawdown: float | None = None,
) -> dict[str, Any]:
    packed = build_enriched_opportunities(
        session,
        as_of=as_of,
        capital=capital,
        equity_expected_return=equity_expected_return,
        equity_expected_excess_return=equity_expected_excess_return,
    )
    budget = get_risk_budget(profile_id)
    hurdle = packed["context"].cbr_hurdle_annual
    market = MarketContext(
        as_of_date=packed["context"].as_of_date,
        available_capital=capital,
        cbr_hurdle_annual=hurdle,
        volatility=volatility,
        drawdown=drawdown,
        liquidity_ok=True,
        data_quality_ok=True,
    )
    decision = InvestmentDecisionEngine().decide(
        equity=packed["equity"],
        fixed_income=packed["fixed_income"],
        cash=packed["cash"],
        risk_budget=budget,
        market=market,
    )
    # Reuse lot preview via a thin adapter AllocationDecision-like weights.
    from app.modules.investment.domain.policy import AllocationDecision

    alloc_like = AllocationDecision(
        policy_id=decision.profile_id,
        equity_weight=decision.equity_weight,
        fixed_income_weight=decision.fixed_income_weight,
        cash_weight=decision.cash_weight,
        reason_codes=decision.reason_codes,
        explanation_ru=" ".join(decision.explanations),
        status=decision.status,
        confidence=None,
        limitations=decision.limitations,
    )
    lots = preview_decision_lots(
        alloc_like,
        capital=capital,
        equity_price=equity_price,
        equity_lot_size=equity_lot_size,
        bond_price=bond_price,
        bond_lot_size=bond_lot_size,
        cost_bps=cost_bps,
    )
    cal: EquityOpportunityCalibration = packed["calibration"]
    return {
        "as_of": packed["context"].as_of_date.isoformat(),
        "capital": str(capital),
        "cbr_hurdle_annual": hurdle,
        "hurdle_20d": horizon_return(hurdle, "20d") if hurdle is not None else None,
        "hurdle_1y": horizon_return(hurdle, "1y") if hurdle is not None else None,
        "profile_id": profile_id,
        "equity_opportunity": asdict(packed["equity"]) if packed["equity"] else None,
        "fixed_income_opportunity": asdict(packed["fixed_income"]) if packed["fixed_income"] else None,
        "cash_opportunity": asdict(packed["cash"]) if packed["cash"] else None,
        "calibration": {
            "sample_size": cal.sample_size,
            "bias": cal.bias,
            "mae": cal.mae,
            "hit_rate": cal.hit_rate,
            "calibration_status": cal.calibration_status.value,
            "uncertainty_note": cal.uncertainty_note,
            "buckets": [asdict(b) for b in cal.buckets],
            "limitations": list(cal.limitations),
        },
        "risk_budget": asdict(budget),
        "decision": _decision_payload(decision),
        "lots": lots,
        "economic_metrics": {
            "return": None,
            "excess_vs_cbr": None,
            "max_drawdown": drawdown,
            "volatility": volatility,
            "turnover": None,
            "question_ru": "Оправдал ли результат риск?",
            "answer_ru": (
                "В V0 метрики результата — research framing. Нет автоматического вердикта-победителя."
            ),
        },
        "bond_safety_reminder": BOND_SAFETY_REMINDER_RU,
        "mode": "RISK_OPPORTUNITY_ENGINE_V0",
    }


def compare_decision_profiles(
    session: Session,
    *,
    capital: Decimal = Decimal("100000"),
    equity_expected_excess_return: float | None = None,
) -> dict[str, Any]:
    comparisons = []
    for profile_id in RISK_BUDGETS:
        payload = run_investment_decision(
            session,
            profile_id=profile_id,
            capital=capital,
            equity_expected_excess_return=equity_expected_excess_return,
        )
        comparisons.append(
            {
                "profile_id": profile_id,
                "decision": payload["decision"],
            }
        )
    # Also show static sleeve benchmarks via existing allocation compare shape.
    from app.modules.investment.application.allocation_service import (
        context_payload,
        decision_payload,
        list_policies,
        run_allocation_policy,
    )

    ctx = build_allocation_context(
        session, capital=capital, equity_expected_excess_return=equity_expected_excess_return
    )
    static = []
    for policy in list_policies():
        d = run_allocation_policy(ctx, policy_id=policy["id"])
        static.append({"policy": policy, "decision": decision_payload(d)})

    return {
        "profiles": comparisons,
        "static_benchmarks": static,
        "cbr_benchmark": {
            "annual_rate": ctx.cbr_hurdle_annual,
            "note": "Cash / CBR hurdle benchmark — not a deposit guarantee",
        },
        "note": "Research comparison only — no automatic winner.",
        "context": context_payload(ctx),
    }


def list_risk_profiles() -> list[dict[str, str]]:
    return [
        {"id": p, "title": p, "kind": "risk_budget_profile"}
        for p in RISK_BUDGETS
    ]


def _decision_payload(decision: InvestmentDecision) -> dict[str, Any]:
    return {
        "profile_id": decision.profile_id,
        "equity_weight": decision.equity_weight,
        "fixed_income_weight": decision.fixed_income_weight,
        "cash_weight": decision.cash_weight,
        "weights_pct": {
            "equity": round(decision.equity_weight * 100, 2),
            "fixed_income": round(decision.fixed_income_weight * 100, 2),
            "cash": round(decision.cash_weight * 100, 2),
        },
        "reason_codes": list(decision.reason_codes),
        "explanations": list(decision.explanations),
        "warnings": list(decision.warnings),
        "status": decision.status.value,
        "why_equity_ru": decision.why_equity_ru,
        "why_fixed_income_ru": decision.why_fixed_income_ru,
        "why_cash_ru": decision.why_cash_ru,
        "limitations": list(decision.limitations),
    }
