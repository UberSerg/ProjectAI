"""Broker accounts + fee profiles API (Personal Broker Integration).

No OAuth / execution / secrets — tariff metadata and estimates only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.db.session import core_session
from app.modules.portfolio.application.broker_fee_service import (
    BrokerFeeError,
    _account_dict,
    _profile_dict,
    create_broker_account,
    create_custom_fee_profile,
    get_broker_account,
    list_broker_accounts,
    list_fee_profiles,
    update_broker_account,
    update_custom_fee_profile,
)

router = APIRouter()


class BrokerAccountCreate(BaseModel):
    name: str
    fee_profile_id: int
    note: str | None = None


class BrokerAccountPatch(BaseModel):
    name: str | None = None
    fee_profile_id: int | None = None
    note: str | None = None
    active: bool | None = None


class FeeProfileCreate(BaseModel):
    name: str
    broker_name: str
    tariff_name: str | None = None
    broker_code: str = "CUSTOM"
    buy_rate_pct: Decimal = Field(ge=0, description="BUY commission in percent points, e.g. 0.3")
    sell_rate_pct: Decimal = Field(ge=0, description="SELL commission in percent points, e.g. 0.3")


class FeeProfilePatch(BaseModel):
    name: str | None = None
    broker_name: str | None = None
    tariff_name: str | None = None
    buy_rate_pct: Decimal | None = Field(default=None, ge=0)
    sell_rate_pct: Decimal | None = Field(default=None, ge=0)


def _http_broker(exc: BrokerFeeError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail={"code": exc.code, "message": exc.message},
    )


@router.get("/fee-profiles")
def get_fee_profiles(include_rules: bool = Query(True)) -> dict[str, Any]:
    with core_session() as session:
        items = list_fee_profiles(session, include_rules=include_rules)
        return {"items": items, "count": len(items)}


@router.post("/fee-profiles")
def post_fee_profile(body: FeeProfileCreate) -> dict[str, Any]:
    with core_session() as session:
        try:
            profile = create_custom_fee_profile(
                session,
                name=body.name,
                broker_name=body.broker_name,
                tariff_name=body.tariff_name,
                buy_rate_pct=body.buy_rate_pct,
                sell_rate_pct=body.sell_rate_pct,
                broker_code=body.broker_code,
            )
            session.refresh(profile, attribute_names=["rules"])
            return _profile_dict(profile, include_rules=True)
        except BrokerFeeError as exc:
            raise _http_broker(exc) from exc


@router.patch("/fee-profiles/{profile_id}")
def patch_fee_profile(profile_id: int, body: FeeProfilePatch) -> dict[str, Any]:
    with core_session() as session:
        try:
            kwargs: dict[str, Any] = {}
            if body.name is not None:
                kwargs["name"] = body.name
            if body.broker_name is not None:
                kwargs["broker_name"] = body.broker_name
            if body.tariff_name is not None:
                kwargs["tariff_name"] = body.tariff_name
            if body.buy_rate_pct is not None:
                kwargs["buy_rate_pct"] = body.buy_rate_pct
            if body.sell_rate_pct is not None:
                kwargs["sell_rate_pct"] = body.sell_rate_pct
            profile = update_custom_fee_profile(session, profile_id, **kwargs)
            return _profile_dict(profile, include_rules=True)
        except BrokerFeeError as exc:
            raise _http_broker(exc) from exc


@router.get("/broker-accounts")
def get_broker_accounts(active_only: bool = Query(True)) -> dict[str, Any]:
    with core_session() as session:
        items = list_broker_accounts(session, active_only=active_only)
        return {"items": items, "count": len(items)}


@router.post("/broker-accounts")
def post_broker_account(body: BrokerAccountCreate) -> dict[str, Any]:
    with core_session() as session:
        try:
            account = create_broker_account(
                session,
                name=body.name,
                fee_profile_id=body.fee_profile_id,
                note=body.note,
            )
            account = get_broker_account(session, int(account.id))
            return _account_dict(account)
        except BrokerFeeError as exc:
            raise _http_broker(exc) from exc


@router.get("/broker-accounts/{account_id}")
def get_one_broker_account(account_id: int) -> dict[str, Any]:
    with core_session() as session:
        try:
            account = get_broker_account(session, account_id)
            return _account_dict(account)
        except BrokerFeeError as exc:
            raise _http_broker(exc) from exc


@router.patch("/broker-accounts/{account_id}")
def patch_broker_account(account_id: int, body: BrokerAccountPatch) -> dict[str, Any]:
    with core_session() as session:
        try:
            kwargs: dict[str, Any] = {}
            if body.name is not None:
                kwargs["name"] = body.name
            if body.fee_profile_id is not None:
                kwargs["fee_profile_id"] = body.fee_profile_id
            if "note" in body.model_fields_set:
                kwargs["note"] = body.note
            if body.active is not None:
                kwargs["active"] = body.active
            account = update_broker_account(session, account_id, **kwargs)
            account = get_broker_account(session, int(account.id))
            return _account_dict(account)
        except BrokerFeeError as exc:
            raise _http_broker(exc) from exc

