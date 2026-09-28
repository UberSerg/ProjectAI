"""Multi-Portfolio V2 APIs — portfolio-id scoped user books."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.db.session import core_session
from app.modules.portfolio.application.daily_personal_decision_service import (
    build_daily_personal_decision,
)
from app.modules.portfolio.application.manual_portfolio_service import (
    LotValidationError,
    advisory_rebalance,
    analyze_manual_portfolio,
    compare_to_candidate,
)
from app.modules.portfolio.application.personal_portfolio_service import (
    PersonalPortfolioError,
    cancel_operation,
    create_operation,
    get_or_create_test_portfolio,
    get_personal_summary,
    reconcile,
)
from app.modules.portfolio.application.user_portfolio_service import (
    activate_portfolio,
    add_draft_position,
    clear_draft_portfolio,
    create_user_portfolio,
    delete_draft_position,
    delete_user_portfolio,
    get_portfolio,
    list_user_portfolios,
    patch_draft_position,
    rename_user_portfolio,
    reset_portfolio,
    set_draft_cash,
)

router = APIRouter()

OpType = Literal[
    "DEPOSIT",
    "WITHDRAWAL",
    "BUY",
    "SELL",
    "COMMISSION",
    "OPENING_CASH",
    "OPENING_POSITION",
]


class PortfolioCreate(BaseModel):
    name: str
    description: str | None = None


class PortfolioPatch(BaseModel):
    name: str | None = None
    description: str | None = None


class DraftCashUpdate(BaseModel):
    cash_rub: Decimal = Field(ge=0)


class DraftPositionCreate(BaseModel):
    instrument_id: int
    units: Decimal | None = None
    lots: Decimal | None = None
    average_price: Decimal | None = None
    cost_basis_total_rub: Decimal | None = None
    note: str | None = None
    non_standard_lot: bool = False


class DraftPositionPatch(BaseModel):
    units: Decimal | None = None
    lots: Decimal | None = None
    average_price: Decimal | None = None
    cost_basis_total_rub: Decimal | None = None
    clear_cost_basis: bool = False
    note: str | None = None
    non_standard_lot: bool | None = None


class OperationCreate(BaseModel):
    operation_type: OpType
    occurred_at: datetime | date | str
    instrument_id: int | None = None
    lots: Decimal | None = None
    units: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    commission: Decimal | None = Field(default=None, ge=0)
    note: str | None = None
    non_standard_lot: bool = False
    idempotency_key: str | None = None
    supersedes_operation_id: int | None = None
    correction_reason: str | None = None


class CancelBody(BaseModel):
    reason: str | None = None
    idempotency_key: str | None = None


def _http(exc: PersonalPortfolioError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail={"code": exc.code, "message": exc.message},
    )


def _resolve(session, portfolio_id: int, *, test: bool):
    if test:
        return get_or_create_test_portfolio(session)
    return get_portfolio(session, portfolio_id, allow_test=False)


@router.get("")
def list_portfolios(
    test: bool = Query(False, description="Include/list test books only via create path"),
) -> dict[str, Any]:
    with core_session() as session:
        items = list_user_portfolios(session, include_test=test)
        return {"items": items, "count": len(items)}


@router.post("")
def create_portfolio(body: PortfolioCreate, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            row = create_user_portfolio(
                session,
                name=body.name,
                description=body.description,
                is_test=test,
            )
            return get_personal_summary(session, row, owner=False)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.get("/{portfolio_id}")
def get_one(
    portfolio_id: int,
    owner: bool = Query(False),
    test: bool = Query(False),
) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            return get_personal_summary(session, portfolio, owner=owner)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.patch("/{portfolio_id}")
def patch_one(portfolio_id: int, body: PortfolioPatch, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            kwargs: dict[str, Any] = {}
            if body.name is not None:
                kwargs["name"] = body.name
            if "description" in body.model_fields_set:
                kwargs["description"] = body.description
            if kwargs:
                rename_user_portfolio(session, portfolio, **kwargs)
            return get_personal_summary(session, portfolio, owner=False)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.delete("/{portfolio_id}")
def delete_one(portfolio_id: int, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            return delete_user_portfolio(session, portfolio)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.put("/{portfolio_id}/draft/cash")
def put_draft_cash(portfolio_id: int, body: DraftCashUpdate, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            set_draft_cash(session, portfolio, body.cash_rub)
            return get_personal_summary(session, portfolio, owner=False)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.post("/{portfolio_id}/draft/positions")
def post_draft_position(
    portfolio_id: int, body: DraftPositionCreate, test: bool = Query(False)
) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            pos = add_draft_position(
                session,
                portfolio,
                instrument_id=body.instrument_id,
                units=body.units,
                lots=body.lots,
                average_price=body.average_price,
                cost_basis_total_rub=body.cost_basis_total_rub,
                note=body.note,
                non_standard_lot=body.non_standard_lot,
            )
            return {
                "id": pos.id,
                "instrument_id": pos.instrument_id,
                "units": float(pos.units),
                "average_price": float(pos.average_price) if pos.average_price is not None else None,
                "note": pos.note,
                "portfolio": get_personal_summary(session, portfolio, owner=False),
            }
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc
        except LotValidationError as exc:
            raise HTTPException(400, {"code": exc.code, "message": str(exc)}) from exc


@router.patch("/{portfolio_id}/draft/positions/{position_id}")
def patch_draft_pos(
    portfolio_id: int,
    position_id: int,
    body: DraftPositionPatch,
    test: bool = Query(False),
) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            pos = patch_draft_position(
                session,
                portfolio,
                position_id,
                units=body.units,
                lots=body.lots,
                average_price=body.average_price,
                cost_basis_total_rub=body.cost_basis_total_rub,
                clear_cost_basis=body.clear_cost_basis,
                note=body.note if "note" in body.model_fields_set else ...,
                non_standard_lot=body.non_standard_lot,
            )
            return {
                "id": pos.id,
                "instrument_id": pos.instrument_id,
                "units": float(pos.units),
                "average_price": float(pos.average_price) if pos.average_price is not None else None,
                "portfolio": get_personal_summary(session, portfolio, owner=False),
            }
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.delete("/{portfolio_id}/draft/positions/{position_id}")
def delete_draft_pos(
    portfolio_id: int, position_id: int, test: bool = Query(False)
) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            result = delete_draft_position(session, portfolio, position_id)
            result["portfolio"] = get_personal_summary(session, portfolio, owner=False)
            return result
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.post("/{portfolio_id}/draft/clear")
def post_draft_clear(portfolio_id: int, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            clear_draft_portfolio(session, portfolio)
            return get_personal_summary(session, portfolio, owner=False)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.post("/{portfolio_id}/activate")
def post_activate(portfolio_id: int, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            return activate_portfolio(session, portfolio)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.post("/{portfolio_id}/reset")
def post_reset(portfolio_id: int, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            return reset_portfolio(session, portfolio)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.get("/{portfolio_id}/reconciliation")
def get_reconciliation(portfolio_id: int, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            return reconcile(session, portfolio)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.get("/{portfolio_id}/daily-decision")
def get_daily_decision(portfolio_id: int, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            return build_daily_personal_decision(session, portfolio=portfolio)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.get("/{portfolio_id}/analysis")
def get_analysis(portfolio_id: int, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            return analyze_manual_portfolio(session, portfolio)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.get("/{portfolio_id}/compare-candidate")
def get_compare(portfolio_id: int, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            result = compare_to_candidate(session, portfolio)
            result["actual_portfolio_id"] = int(portfolio.id)
            result["actual_portfolio_name"] = portfolio.name
            return result
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.get("/{portfolio_id}/rebalance")
def get_rebalance(portfolio_id: int, test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            result = advisory_rebalance(session, portfolio)
            result["actual_portfolio_id"] = int(portfolio.id)
            result["actual_portfolio_name"] = portfolio.name
            return result
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.get("/{portfolio_id}/cashflows")
def get_cashflows(portfolio_id: int, test: bool = Query(False)) -> dict[str, Any]:
    from app.modules.investment.application.portfolio_cashflow_service import (
        build_manual_portfolio_cashflows,
    )

    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            return build_manual_portfolio_cashflows(session, portfolio=portfolio)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.post("/{portfolio_id}/operations")
def post_operation(
    portfolio_id: int,
    body: OperationCreate,
    test: bool = Query(False),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            op = create_operation(
                session,
                portfolio=portfolio,
                operation_type=body.operation_type,
                occurred_at=body.occurred_at,
                idempotency_key=body.idempotency_key or idempotency_key,
                instrument_id=body.instrument_id,
                lots=body.lots,
                units=body.units,
                price=body.price,
                amount=body.amount,
                commission=body.commission,
                note=body.note,
                non_standard_lot=body.non_standard_lot,
                supersedes_operation_id=body.supersedes_operation_id,
                correction_reason=body.correction_reason,
            )
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc
        summary = get_personal_summary(session, portfolio, owner=True)
        return {"operation_id": op.id, "portfolio": summary}


@router.post("/{portfolio_id}/operations/{operation_id}/cancel")
def post_cancel(
    portfolio_id: int,
    operation_id: int,
    body: CancelBody,
    test: bool = Query(False),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    with core_session() as session:
        try:
            portfolio = _resolve(session, portfolio_id, test=test)
            op = cancel_operation(
                session,
                portfolio=portfolio,
                operation_id=operation_id,
                reason=body.reason,
                idempotency_key=body.idempotency_key or idempotency_key,
            )
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc
        return {
            "cancelled_operation_id": op.id,
            "portfolio": get_personal_summary(session, portfolio, owner=True),
        }
