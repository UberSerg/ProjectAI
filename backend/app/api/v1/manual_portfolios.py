"""Manual Portfolio V1 APIs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.infrastructure.db.session import core_session
from app.modules.portfolio.application.manual_portfolio_service import (
    LotValidationError,
    add_position,
    advisory_rebalance,
    analyze_manual_portfolio,
    compare_to_candidate,
    delete_position,
    get_or_create_primary,
    patch_position,
    portfolio_to_dict,
    update_cash,
)

router = APIRouter()


class CashUpdate(BaseModel):
    cash_rub: Decimal = Field(ge=0)


class PositionCreate(BaseModel):
    instrument_id: int
    units: Decimal
    average_price: Decimal | None = None
    note: str | None = None
    non_standard_lot: bool = False


class PositionPatch(BaseModel):
    units: Decimal | None = None
    average_price: Decimal | None = None
    note: str | None = None
    non_standard_lot: bool | None = None


@router.get("/primary")
def get_primary_manual_portfolio() -> dict[str, Any]:
    with core_session() as session:
        portfolio = get_or_create_primary(session)
        return portfolio_to_dict(portfolio)


@router.put("/primary/cash")
def put_primary_cash(body: CashUpdate) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = update_cash(session, body.cash_rub)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return portfolio_to_dict(portfolio)


@router.post("/primary/positions")
def post_primary_position(body: PositionCreate) -> dict[str, Any]:
    with core_session() as session:
        try:
            pos = add_position(
                session,
                instrument_id=body.instrument_id,
                units=body.units,
                average_price=body.average_price,
                note=body.note,
                non_standard_lot=body.non_standard_lot,
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except LotValidationError as exc:
            raise HTTPException(400, {"code": exc.code, "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "id": pos.id,
            "instrument_id": pos.instrument_id,
            "units": float(pos.units),
            "average_price": float(pos.average_price) if pos.average_price is not None else None,
            "note": pos.note,
            "non_standard_lot": bool(pos.non_standard_lot),
        }


@router.patch("/primary/positions/{position_id}")
def patch_primary_position(position_id: int, body: PositionPatch) -> dict[str, Any]:
    with core_session() as session:
        try:
            pos = patch_position(
                session,
                position_id,
                units=body.units,
                average_price=body.average_price,
                note=body.note,
                non_standard_lot=body.non_standard_lot,
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except LotValidationError as exc:
            raise HTTPException(400, {"code": exc.code, "message": str(exc)}) from exc
        return {
            "id": pos.id,
            "instrument_id": pos.instrument_id,
            "units": float(pos.units),
            "average_price": float(pos.average_price) if pos.average_price is not None else None,
            "note": pos.note,
            "non_standard_lot": bool(pos.non_standard_lot),
        }


@router.delete("/primary/positions/{position_id}")
def delete_primary_position(position_id: int) -> dict[str, Any]:
    with core_session() as session:
        try:
            delete_position(session, position_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"status": "DELETED", "id": position_id}


@router.get("/primary/analysis")
def get_primary_analysis() -> dict[str, Any]:
    with core_session() as session:
        return analyze_manual_portfolio(session)


@router.get("/primary/compare-candidate")
def get_primary_compare_candidate() -> dict[str, Any]:
    with core_session() as session:
        return compare_to_candidate(session)


@router.get("/primary/rebalance")
def get_primary_rebalance() -> dict[str, Any]:
    with core_session() as session:
        return advisory_rebalance(session)


@router.get("/primary/cashflows")
def get_primary_cashflows() -> dict[str, Any]:
    """Portfolio Cashflow Intelligence V1 — 30d/90d/12m gross bond payments."""
    from app.modules.investment.application.portfolio_cashflow_service import (
        build_manual_portfolio_cashflows,
    )

    with core_session() as session:
        return build_manual_portfolio_cashflows(session)
