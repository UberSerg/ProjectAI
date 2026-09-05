"""Read-only investment foundation and research allocation preview API."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.db.session import core_session
from app.modules.investment.application.allocation_service import (
    allocation_foundation_readiness,
    build_allocation_context,
    context_payload,
    create_allocation_research_run_contract,
    decision_payload,
    economic_verdict_placeholder,
    list_policies,
    preview_decision_lots,
    run_allocation_policy,
)
from app.modules.investment.application.services import (
    CbrHurdleProvider,
    fixed_income_readiness,
    investment_readiness,
    list_bonds,
)
from app.modules.investment.domain.allocation import (
    AllocationCandidate,
    AssetSleeve,
    allocate_integer_lots,
)
from app.modules.investment.domain.fixed_income import TransactionCostProfile
from app.modules.investment.domain.hurdle import horizon_return
from app.modules.investment.domain.policy import AllocationConstraints, PolicyId

router = APIRouter()


class AllocationCandidateRequest(BaseModel):
    symbol: str
    sleeve: AssetSleeve
    price: Decimal = Field(gt=0)
    lot_size: int = Field(gt=0)
    target_weight: Decimal = Field(ge=0, le=1)


class AllocationPreviewRequest(BaseModel):
    capital: Decimal = Field(default=Decimal("100000"), ge=0)
    cost_bps: Decimal = Field(default=Decimal("5"), ge=0)
    min_fee: Decimal = Field(default=Decimal("0"), ge=0)
    candidates: list[AllocationCandidateRequest]


class AllocationDecideRequest(BaseModel):
    policy_id: str = PolicyId.CBR_HURDLE_GATE_V0.value
    capital: Decimal = Field(default=Decimal("100000"), ge=0)
    as_of: date | None = None
    equity_expected_return: float | None = None
    equity_expected_excess_return: float | None = None
    equity_model_source: str | None = None
    required_equity_premium: float = 0.0
    equity_price: Decimal = Field(default=Decimal("300"), gt=0)
    equity_lot_size: int = Field(default=10, gt=0)
    bond_price: Decimal = Field(default=Decimal("980"), gt=0)
    bond_lot_size: int = Field(default=1, gt=0)
    cost_bps: Decimal = Field(default=Decimal("5"), ge=0)
    min_cash: float = Field(default=0.0, ge=0, le=1)
    max_equity_weight: float = Field(default=1.0, ge=0, le=1)


@router.get("/investment/hurdle")
def investment_hurdle(
    as_of: Annotated[date | None, Query()] = None,
    horizon: Annotated[str, Query()] = "1y",
) -> dict[str, Any]:
    effective_date = as_of or date.today()
    with core_session() as session:
        quote = CbrHurdleProvider(session).quote(effective_date)
    if quote is None:
        return {"status": "NOT_READY", "as_of": effective_date, "reason": "KEY_RATE unavailable"}
    payload = asdict(quote)
    payload["status"] = "READY"
    payload["horizon"] = horizon
    payload["hurdle_return"] = horizon_return(quote.annual_rate, horizon)
    payload["hurdle_20d"] = horizon_return(quote.annual_rate, "20d")
    payload["hurdle_1y"] = horizon_return(quote.annual_rate, "1y")
    payload["disclaimer"] = (
        "Ключевая ставка — динамический экономический порог, а не гарантированная "
        "депозитная доходность. Результаты — после торговых издержек, до налогов."
    )
    return payload


@router.get("/investment/readiness")
def readiness() -> dict[str, Any]:
    with core_session() as session:
        return investment_readiness(session)


@router.get("/fixed-income/instruments")
def fixed_income_instruments(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    with core_session() as session:
        items = list_bonds(session, limit)
    return {"items": items, "count": len(items)}


@router.get("/fixed-income/overview")
def fixed_income_overview() -> dict[str, Any]:
    with core_session() as session:
        report = fixed_income_readiness(session)
    return {
        **report,
        "scope": "VANILLA_RUB_FIXED_RATE_RESEARCH",
        "boards": ["TQOB", "TQCB"],
    }


@router.get("/fixed-income/readiness")
def fixed_income_readiness_endpoint() -> dict[str, Any]:
    with core_session() as session:
        return fixed_income_readiness(session)


@router.post("/portfolio/allocation/preview")
def allocation_preview(request: AllocationPreviewRequest) -> dict[str, Any]:
    profile = TransactionCostProfile(request.cost_bps, min_fee=request.min_fee)
    result = allocate_integer_lots(
        [
            AllocationCandidate(
                symbol=row.symbol,
                sleeve=row.sleeve,
                price=row.price,
                lot_size=row.lot_size,
                target_weight=row.target_weight,
            )
            for row in request.candidates
        ],
        capital=request.capital,
        costs=profile,
    )
    return asdict(result)


@router.get("/allocation/policies")
def allocation_policies() -> dict[str, Any]:
    return {"policies": list_policies()}


@router.get("/allocation/readiness")
def allocation_readiness() -> dict[str, Any]:
    with core_session() as session:
        return allocation_foundation_readiness(session)


@router.post("/allocation/decide")
def allocation_decide(request: AllocationDecideRequest) -> dict[str, Any]:
    try:
        with core_session() as session:
            context = build_allocation_context(
                session,
                as_of=request.as_of,
                capital=request.capital,
                equity_expected_return=request.equity_expected_return,
                equity_expected_excess_return=request.equity_expected_excess_return,
                equity_model_source=request.equity_model_source,
                required_equity_premium=request.required_equity_premium,
                constraints=AllocationConstraints(
                    max_equity_weight=request.max_equity_weight,
                    min_cash=request.min_cash,
                ),
            )
            decision = run_allocation_policy(context, policy_id=request.policy_id)
            lots = preview_decision_lots(
                decision,
                capital=request.capital,
                equity_price=request.equity_price,
                equity_lot_size=request.equity_lot_size,
                bond_price=request.bond_price,
                bond_lot_size=request.bond_lot_size,
                cost_bps=request.cost_bps,
            )
            return {
                "context": context_payload(context),
                "decision": decision_payload(decision),
                "lots": lots,
                "economic_verdict": asdict(
                    economic_verdict_placeholder(
                        cbr_hurdle_return=(
                            horizon_return(context.cbr_hurdle_annual, "1y")
                            if context.cbr_hurdle_annual is not None
                            else None
                        )
                    )
                ),
                "mode": "RESEARCH_PREVIEW_V0",
            }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/allocation/compare")
def allocation_compare(
    capital: Annotated[Decimal, Query(ge=0)] = Decimal("100000"),
    equity_expected_excess_return: Annotated[float | None, Query()] = None,
) -> dict[str, Any]:
    """Compare Equity-only / FI-only / Cash / Gate policies — no automatic winner."""
    with core_session() as session:
        context = build_allocation_context(
            session,
            capital=capital,
            equity_expected_excess_return=equity_expected_excess_return,
        )
        comparisons = []
        for policy in list_policies():
            decision = run_allocation_policy(context, policy_id=policy["id"])
            comparisons.append(
                {
                    "policy": policy,
                    "decision": decision_payload(decision),
                }
            )
    return {
        "context": context_payload(context),
        "comparisons": comparisons,
        "note": "Research comparison only — Kraken does not auto-select a winner in V0.",
    }


@router.post("/allocation/research-run")
def allocation_research_run(
    policy_id: Annotated[str, Query()] = PolicyId.CBR_HURDLE_GATE_V0.value,
    as_of_from: Annotated[date | None, Query()] = None,
    as_of_to: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    run = create_allocation_research_run_contract(policy_id=policy_id, as_of_from=as_of_from, as_of_to=as_of_to)
    return asdict(run)
