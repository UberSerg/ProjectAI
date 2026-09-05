"""Read-only investment foundation and research allocation preview API."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.infrastructure.db.session import core_session
from app.modules.investment.application.services import (
    CbrHurdleProvider,
    bond_accounting_preview,
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


@router.get("/fixed-income/instruments/{symbol}/accounting-preview")
def fixed_income_accounting_preview(
    symbol: str,
    lots: Annotated[int, Query(ge=1, le=1000)] = 1,
    cost_bps: Annotated[Decimal, Query(ge=0)] = Decimal("5"),
) -> dict[str, Any]:
    with core_session() as session:
        return bond_accounting_preview(session, symbol=symbol.upper(), lots=lots, cost_bps=cost_bps)


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
