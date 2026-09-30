"""Personal Decision Memory V1 APIs (mounted under /personal-portfolios).

Reads Core (portfolio, prices, operations) and writes Memory DB only.
``GET daily-decision`` stays read-only: capture happens only via POST here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.v1.personal_portfolios import _http, _resolve
from app.infrastructure.db.session import core_session, memory_session
from app.modules.memory.application.decision_memory_service import (
    DecisionMemoryError,
    capture_decision,
    confirm_operation_link,
    find_existing_capture,
    get_decision,
    get_summary,
    list_decisions,
    list_possible_operation_matches,
    refresh_outcomes,
    unlink_operation_link,
)
from app.modules.portfolio.application.daily_personal_decision_service import (
    build_daily_personal_decision,
)
from app.modules.portfolio.application.personal_portfolio_service import PersonalPortfolioError

router = APIRouter()


class CaptureBody(BaseModel):
    # ``captured_at`` is deliberately absent: the server clock is the only source.
    new_cash_rub: Decimal | None = Field(default=None, ge=0)
    expected_decision_fingerprint: str = Field(min_length=1)


class LinkBody(BaseModel):
    personal_operation_id: int


def _http_memory(exc: DecisionMemoryError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post("/{portfolio_id}/decision-memory/capture")
def post_capture(
    portfolio_id: int,
    body: CaptureBody,
    test: Annotated[bool, Query()] = False,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    new_cash = body.new_cash_rub
    expected_fp = body.expected_decision_fingerprint
    with core_session() as core, memory_session() as mem:
        try:
            portfolio = _resolve(core, portfolio_id, test=test)
            # Replay BEFORE rebuild so a successful capture stays stable if the
            # live Daily Decision has since changed.
            replay = find_existing_capture(
                mem,
                portfolio_id=int(portfolio.id),
                idempotency_key=idempotency_key or "",
                new_cash_rub=new_cash,
                expected_decision_fingerprint=expected_fp,
            )
            if replay is not None:
                return replay
            decision = build_daily_personal_decision(
                core,
                portfolio=portfolio,
                new_cash_rub=new_cash if new_cash is not None else Decimal("0"),
            )
            return capture_decision(
                mem,
                core,
                portfolio_id=int(portfolio.id),
                decision_payload=decision,
                idempotency_key=idempotency_key or "",
                new_cash_rub=new_cash,
                expected_decision_fingerprint=expected_fp,
            )
        except DecisionMemoryError as exc:
            raise _http_memory(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.get("/{portfolio_id}/decision-memory")
def get_list(
    portfolio_id: int,
    test: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    with core_session() as core, memory_session() as mem:
        try:
            portfolio = _resolve(core, portfolio_id, test=test)
            return list_decisions(mem, int(portfolio.id), limit)
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


# NOTE: literal segments must be declared before ``/{decision_id}``.
@router.get("/{portfolio_id}/decision-memory/summary")
def get_memory_summary(portfolio_id: int, test: Annotated[bool, Query()] = False) -> dict[str, Any]:
    with core_session() as core, memory_session() as mem:
        try:
            portfolio = _resolve(core, portfolio_id, test=test)
            return get_summary(mem, int(portfolio.id))
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.post("/{portfolio_id}/decision-memory/outcomes/refresh")
def post_refresh_outcomes(portfolio_id: int, test: Annotated[bool, Query()] = False) -> dict[str, Any]:
    with core_session() as core, memory_session() as mem:
        try:
            portfolio = _resolve(core, portfolio_id, test=test)
            return refresh_outcomes(mem, core, int(portfolio.id))
        except DecisionMemoryError as exc:
            raise _http_memory(exc) from exc
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.get("/{portfolio_id}/decision-memory/actions/{action_id}/possible-matches")
def get_possible_matches(portfolio_id: int, action_id: int, test: Annotated[bool, Query()] = False) -> dict[str, Any]:
    with core_session() as core, memory_session() as mem:
        try:
            portfolio = _resolve(core, portfolio_id, test=test)
            return list_possible_operation_matches(mem, core, int(portfolio.id), action_id)
        except DecisionMemoryError as exc:
            raise _http_memory(exc) from exc
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.post("/{portfolio_id}/decision-memory/actions/{action_id}/links")
def post_link(
    portfolio_id: int,
    action_id: int,
    body: LinkBody,
    test: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    with core_session() as core, memory_session() as mem:
        try:
            portfolio = _resolve(core, portfolio_id, test=test)
            return confirm_operation_link(
                mem,
                core,
                portfolio_id=int(portfolio.id),
                decision_action_id=action_id,
                personal_operation_id=body.personal_operation_id,
            )
        except DecisionMemoryError as exc:
            raise _http_memory(exc) from exc
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.delete("/{portfolio_id}/decision-memory/links/{link_id}")
def delete_link(portfolio_id: int, link_id: int, test: Annotated[bool, Query()] = False) -> dict[str, Any]:
    with core_session() as core, memory_session() as mem:
        try:
            portfolio = _resolve(core, portfolio_id, test=test)
            return unlink_operation_link(mem, portfolio_id=int(portfolio.id), link_id=link_id)
        except DecisionMemoryError as exc:
            raise _http_memory(exc) from exc
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc


@router.get("/{portfolio_id}/decision-memory/{decision_id}")
def get_one_decision(portfolio_id: int, decision_id: int, test: Annotated[bool, Query()] = False) -> dict[str, Any]:
    with core_session() as core, memory_session() as mem:
        try:
            portfolio = _resolve(core, portfolio_id, test=test)
            return get_decision(mem, int(portfolio.id), decision_id)
        except DecisionMemoryError as exc:
            raise _http_memory(exc) from exc
        except PersonalPortfolioError as exc:
            raise _http(exc) from exc
