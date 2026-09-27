"""Personal Portfolio V1 APIs (journal-based real book)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.db.session import core_session
from app.modules.portfolio.application.personal_portfolio_service import (
    PersonalPortfolioError,
    activate_journal,
    cancel_operation,
    create_operation,
    get_or_create_primary,
    get_or_create_test_portfolio,
    get_personal_summary,
    reconcile,
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


def _portfolio(session, *, test: bool):
    return get_or_create_test_portfolio(session) if test else get_or_create_primary(session)


@router.get("/primary")
def get_primary_personal(
    owner: bool = Query(False),
    test: bool = Query(False, description="Use isolated TEST portfolio (never the real book)"),
) -> dict[str, Any]:
    with core_session() as session:
        portfolio = _portfolio(session, test=test)
        return get_personal_summary(session, portfolio, owner=owner)


@router.get("/primary/reconciliation")
def get_primary_reconciliation(test: bool = Query(False)) -> dict[str, Any]:
    with core_session() as session:
        portfolio = _portfolio(session, test=test)
        return reconcile(session, portfolio)


@router.post("/primary/activate-journal")
def post_activate_journal(
    test: bool = Query(False, description="Use isolated TEST portfolio (never the real book)"),
) -> dict[str, Any]:
    """Explicit legacy Manual → journal cutover (OPENING_* only; no trade)."""
    with core_session() as session:
        portfolio = _portfolio(session, test=test)
        try:
            return activate_journal(session, portfolio)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.post("/primary/operations")
def post_primary_operation(
    body: OperationCreate,
    test: bool = Query(False),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    with core_session() as session:
        portfolio = _portfolio(session, test=test)
        try:
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


@router.post("/primary/operations/{operation_id}/cancel")
def post_cancel_operation(
    operation_id: int,
    body: CancelBody,
    test: bool = Query(False),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    with core_session() as session:
        portfolio = _portfolio(session, test=test)
        try:
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
