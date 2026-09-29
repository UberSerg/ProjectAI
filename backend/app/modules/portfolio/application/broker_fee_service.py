"""Broker accounts, fee profiles, and FeeEngine-backed commission estimates.

Personal/Shadow callers use this application layer — domain FeeEngine stays pure.
No OAuth, secrets, or broker execution.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.infrastructure.market.models import Instrument
from app.modules.portfolio.domain.fee_engine import (
    FeeEngine,
    FeeEstimate,
    FeeEstimateContext,
    FeeRuleSpec,
    FeeStatus,
    FeeType,
)
from app.modules.portfolio.domain.personal_ledger import ZERO, money
from app.modules.portfolio.infrastructure.models import (
    BrokerAccount,
    FeeProfile,
    FeeRule,
    ManualPortfolio,
    PersonalOperation,
)

CommissionSource = Literal["NONE", "MANUAL", "PROFILE_ESTIMATE"]

CUSTOM_PROFILE_CODE_PREFIX = "CUSTOM_"


class BrokerFeeError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _d(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def fee_rule_to_spec(rule: FeeRule) -> FeeRuleSpec:
    return FeeRuleSpec(
        id=int(rule.id) if rule.id is not None else None,
        code=rule.code,
        market=rule.market,
        trading_system=rule.trading_system,
        execution_channel=rule.execution_channel,
        side=rule.side,
        asset_class=rule.asset_class,
        instrument_subtype=rule.instrument_subtype,
        instrument_id=int(rule.instrument_id) if rule.instrument_id is not None else None,
        instrument_symbol=rule.instrument_symbol,
        turnover_from=rule.turnover_from,
        turnover_to=rule.turnover_to,
        fee_type=rule.fee_type or FeeType.PERCENTAGE,
        percentage_rate=rule.percentage_rate,
        fixed_amount=rule.fixed_amount,
        exclude_from_turnover=bool(rule.exclude_from_turnover),
        priority=int(rule.priority or 100),
        valid_from=rule.valid_from,
        valid_to=rule.valid_to,
        explanation=rule.explanation,
        active=bool(rule.active),
    )


def load_fee_engine(session: Session, fee_profile_id: int) -> FeeEngine:
    rules = list(
        session.scalars(
            select(FeeRule).where(
                FeeRule.fee_profile_id == int(fee_profile_id),
                FeeRule.active.is_(True),
            )
        ).all()
    )
    return FeeEngine([fee_rule_to_spec(r) for r in rules])


def broker_account_day_turnover(
    session: Session,
    *,
    broker_account_id: int,
    as_of: date,
    exclude_operation_id: int | None = None,
) -> Decimal:
    """Same-day clean notional across portfolios on this BrokerAccount.

    Excludes NKD (not modelled on personal ops) and trades whose matched fee rule
    has ``exclude_from_turnover``.
    """
    start = datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC)
    end = datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59, 999999, tzinfo=UTC)
    ops = list(
        session.scalars(
            select(PersonalOperation)
            .where(
                PersonalOperation.broker_account_id == int(broker_account_id),
                PersonalOperation.status == "ACTIVE",
                PersonalOperation.operation_type.in_(("BUY", "SELL")),
                PersonalOperation.occurred_at >= start,
                PersonalOperation.occurred_at <= end,
            )
        ).all()
    )
    exclude_rule_ids: set[int] = set()
    rule_ids = {int(op.fee_rule_id) for op in ops if op.fee_rule_id is not None}
    if rule_ids:
        for rid, excl in session.execute(
            select(FeeRule.id, FeeRule.exclude_from_turnover).where(FeeRule.id.in_(rule_ids))
        ):
            if excl:
                exclude_rule_ids.add(int(rid))

    total = ZERO
    for op in ops:
        if exclude_operation_id is not None and int(op.id) == int(exclude_operation_id):
            continue
        if op.fee_rule_id is not None and int(op.fee_rule_id) in exclude_rule_ids:
            continue
        notional = _trade_notional(op)
        if notional > ZERO:
            total = money(total + notional)
    return total


def _trade_notional(op: PersonalOperation) -> Decimal:
    if op.units is not None and op.price is not None:
        return money(_d(op.units) * _d(op.price))
    if op.amount is not None:
        return money(op.amount)
    return ZERO


def _profile_dict(profile: FeeProfile, *, include_rules: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": int(profile.id),
        "code": profile.code,
        "name": profile.name,
        "broker_code": profile.broker_code,
        "broker_name": profile.broker_name,
        "tariff_name": profile.tariff_name,
        "version": int(profile.version),
        "valid_from": profile.valid_from.isoformat() if profile.valid_from else None,
        "valid_to": profile.valid_to.isoformat() if profile.valid_to else None,
        "source_url": profile.source_url,
        "source_note": profile.source_note,
        "is_builtin": bool(profile.is_builtin),
        "read_only": bool(profile.read_only),
    }
    if include_rules:
        rules = list(profile.rules) if profile.rules is not None else []
        row["rules"] = [
            {
                "id": int(r.id),
                "code": r.code,
                "side": r.side,
                "market": r.market,
                "execution_channel": r.execution_channel,
                "instrument_symbol": r.instrument_symbol,
                "fee_type": r.fee_type,
                "percentage_rate": str(r.percentage_rate) if r.percentage_rate is not None else None,
                "fixed_amount": str(r.fixed_amount) if r.fixed_amount is not None else None,
                "exclude_from_turnover": bool(r.exclude_from_turnover),
                "priority": int(r.priority),
                "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                "valid_to": r.valid_to.isoformat() if r.valid_to else None,
                "explanation": r.explanation,
                "active": bool(r.active),
            }
            for r in sorted(rules, key=lambda x: (x.priority, x.id or 0))
        ]
        buy_pct, sell_pct = _side_rates_from_rules(rules)
        row["buy_rate_pct"] = str(buy_pct) if buy_pct is not None else None
        row["sell_rate_pct"] = str(sell_pct) if sell_pct is not None else None
    return row


def _side_rates_from_rules(rules: list[FeeRule]) -> tuple[Decimal | None, Decimal | None]:
    """Extract simple BUY%/SELL% for custom profiles (percent points, e.g. 0.3)."""
    buy: Decimal | None = None
    sell: Decimal | None = None
    for r in rules:
        if not r.active or r.percentage_rate is None:
            continue
        side = (r.side or "ANY").upper()
        pct = money(_d(r.percentage_rate) * Decimal("100"))
        if side in {"BUY", "ANY"} and buy is None:
            buy = pct
        if side in {"SELL", "ANY"} and sell is None:
            sell = pct
    return buy, sell


def _account_dict(account: BrokerAccount, *, include_profile: bool = True) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": int(account.id),
        "name": account.name,
        "broker_code": account.broker_code,
        "broker_name": account.broker_name,
        "tariff_name": account.tariff_name,
        "fee_profile_id": int(account.fee_profile_id),
        "base_currency": account.base_currency,
        "active": bool(account.active),
        "note": account.note,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }
    if include_profile and account.fee_profile is not None:
        row["fee_profile"] = _profile_dict(account.fee_profile, include_rules=False)
    return row


def broker_summary_for_portfolio(session: Session, portfolio: ManualPortfolio) -> dict[str, Any] | None:
    if portfolio.broker_account_id is None:
        return None
    account = session.scalar(
        select(BrokerAccount)
        .options(selectinload(BrokerAccount.fee_profile))
        .where(BrokerAccount.id == int(portfolio.broker_account_id))
    )
    if account is None:
        return None
    profile = account.fee_profile
    return {
        "broker_account_id": int(account.id),
        "broker_account_name": account.name,
        "broker_code": account.broker_code,
        "broker_name": account.broker_name,
        "tariff_name": account.tariff_name or (profile.tariff_name if profile else None),
        "fee_profile_id": int(account.fee_profile_id),
        "fee_profile_code": profile.code if profile else None,
        "fee_profile_name": profile.name if profile else None,
        "is_builtin": bool(profile.is_builtin) if profile else False,
        "read_only": bool(profile.read_only) if profile else False,
    }


def list_fee_profiles(session: Session, *, include_rules: bool = True) -> list[dict[str, Any]]:
    q = select(FeeProfile).order_by(FeeProfile.is_builtin.desc(), FeeProfile.code, FeeProfile.version)
    if include_rules:
        q = q.options(selectinload(FeeProfile.rules))
    rows = list(session.scalars(q).all())
    return [_profile_dict(p, include_rules=include_rules) for p in rows]


def list_broker_accounts(session: Session, *, active_only: bool = True) -> list[dict[str, Any]]:
    q = (
        select(BrokerAccount)
        .options(selectinload(BrokerAccount.fee_profile))
        .order_by(BrokerAccount.active.desc(), BrokerAccount.name, BrokerAccount.id)
    )
    if active_only:
        q = q.where(BrokerAccount.active.is_(True))
    return [_account_dict(a) for a in session.scalars(q).all()]


def get_broker_account(session: Session, account_id: int) -> BrokerAccount:
    account = session.scalar(
        select(BrokerAccount)
        .options(selectinload(BrokerAccount.fee_profile).selectinload(FeeProfile.rules))
        .where(BrokerAccount.id == int(account_id))
    )
    if account is None:
        raise BrokerFeeError("BROKER_ACCOUNT_NOT_FOUND", "Брокерский счёт не найден", http_status=404)
    return account


def create_broker_account(
    session: Session,
    *,
    name: str,
    fee_profile_id: int,
    note: str | None = None,
) -> BrokerAccount:
    cleaned = (name or "").strip()
    if not cleaned:
        raise BrokerFeeError("INVALID_NAME", "Укажите название брокерского счёта")
    profile = session.get(FeeProfile, int(fee_profile_id))
    if profile is None:
        raise BrokerFeeError("FEE_PROFILE_NOT_FOUND", "Тарифный профиль не найден", http_status=404)
    account = BrokerAccount(
        name=cleaned,
        broker_code=profile.broker_code,
        broker_name=profile.broker_name,
        tariff_name=profile.tariff_name,
        fee_profile_id=int(profile.id),
        base_currency="RUB",
        active=True,
        note=(note or "").strip() or None,
    )
    session.add(account)
    session.flush()
    session.refresh(account, attribute_names=["fee_profile"])
    return account


def update_broker_account(
    session: Session,
    account_id: int,
    *,
    name: str | None = None,
    fee_profile_id: int | None = None,
    note: str | None | object = ...,
    active: bool | None = None,
) -> BrokerAccount:
    account = get_broker_account(session, account_id)
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise BrokerFeeError("INVALID_NAME", "Укажите название брокерского счёта")
        account.name = cleaned
    if fee_profile_id is not None:
        profile = session.get(FeeProfile, int(fee_profile_id))
        if profile is None:
            raise BrokerFeeError("FEE_PROFILE_NOT_FOUND", "Тарифный профиль не найден", http_status=404)
        account.fee_profile_id = int(profile.id)
        account.broker_code = profile.broker_code
        account.broker_name = profile.broker_name
        account.tariff_name = profile.tariff_name
    if note is not ...:
        account.note = (str(note).strip() or None) if note is not None else None
    if active is not None:
        account.active = bool(active)
    account.updated_at = datetime.now(UTC)
    session.flush()
    return account


def assign_broker_account(
    session: Session,
    portfolio: ManualPortfolio,
    broker_account_id: int | None,
) -> ManualPortfolio:
    if broker_account_id is None:
        portfolio.broker_account_id = None
        portfolio.updated_at = datetime.now(UTC)
        session.flush()
        return portfolio
    account = session.get(BrokerAccount, int(broker_account_id))
    if account is None or not account.active:
        raise BrokerFeeError(
            "BROKER_ACCOUNT_NOT_FOUND",
            "Брокерский счёт не найден или отключён",
            http_status=404,
        )
    portfolio.broker_account_id = int(account.id)
    portfolio.updated_at = datetime.now(UTC)
    session.flush()
    return portfolio


def _pct_to_rate(pct: Decimal) -> Decimal:
    """UI percent points (0.3) → FeeEngine fraction (0.003)."""
    rate = money(_d(pct) / Decimal("100"))
    if rate < ZERO:
        raise BrokerFeeError("INVALID_RATE", "Ставка комиссии не может быть отрицательной")
    return rate


def create_custom_fee_profile(
    session: Session,
    *,
    name: str,
    broker_name: str,
    tariff_name: str | None = None,
    buy_rate_pct: Decimal,
    sell_rate_pct: Decimal,
    broker_code: str = "CUSTOM",
) -> FeeProfile:
    cleaned_name = (name or "").strip()
    cleaned_broker = (broker_name or "").strip()
    if not cleaned_name:
        raise BrokerFeeError("INVALID_NAME", "Укажите название тарифа")
    if not cleaned_broker:
        raise BrokerFeeError("INVALID_BROKER_NAME", "Укажите название брокера")
    buy_rate = _pct_to_rate(buy_rate_pct)
    sell_rate = _pct_to_rate(sell_rate_pct)

    # Unique code: CUSTOM_<n>
    existing = session.scalar(
        select(func.count()).select_from(FeeProfile).where(FeeProfile.code.like(f"{CUSTOM_PROFILE_CODE_PREFIX}%"))
    )
    code = f"{CUSTOM_PROFILE_CODE_PREFIX}{(int(existing or 0) + 1):04d}"

    profile = FeeProfile(
        code=code,
        name=cleaned_name,
        broker_code=(broker_code or "CUSTOM").strip().upper()[:32] or "CUSTOM",
        broker_name=cleaned_broker,
        tariff_name=(tariff_name or cleaned_name).strip(),
        version=1,
        valid_from=date(2026, 1, 1),
        source_note="User-defined custom BUY%/SELL% profile",
        is_builtin=False,
        read_only=False,
    )
    session.add(profile)
    session.flush()

    session.add(
        FeeRule(
            fee_profile_id=int(profile.id),
            code=f"{code}_BUY",
            market="MOEX",
            execution_channel="ONLINE",
            side="BUY",
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=buy_rate,
            exclude_from_turnover=False,
            priority=100,
            valid_from=date(2026, 1, 1),
            explanation=f"Custom BUY rate {buy_rate_pct}% of clean notional",
            active=True,
        )
    )
    session.add(
        FeeRule(
            fee_profile_id=int(profile.id),
            code=f"{code}_SELL",
            market="MOEX",
            execution_channel="ONLINE",
            side="SELL",
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=sell_rate,
            exclude_from_turnover=False,
            priority=100,
            valid_from=date(2026, 1, 1),
            explanation=f"Custom SELL rate {sell_rate_pct}% of clean notional",
            active=True,
        )
    )
    session.flush()
    session.refresh(profile, attribute_names=["rules"])
    return profile


def update_custom_fee_profile(
    session: Session,
    profile_id: int,
    *,
    name: str | None = None,
    broker_name: str | None = None,
    tariff_name: str | None = None,
    buy_rate_pct: Decimal | None = None,
    sell_rate_pct: Decimal | None = None,
) -> FeeProfile:
    profile = session.scalar(
        select(FeeProfile)
        .options(selectinload(FeeProfile.rules))
        .where(FeeProfile.id == int(profile_id))
    )
    if profile is None:
        raise BrokerFeeError("FEE_PROFILE_NOT_FOUND", "Тарифный профиль не найден", http_status=404)
    if profile.is_builtin or profile.read_only:
        raise BrokerFeeError(
            "FEE_PROFILE_READ_ONLY",
            "Встроенный тариф нельзя изменять",
            http_status=409,
        )
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise BrokerFeeError("INVALID_NAME", "Укажите название тарифа")
        profile.name = cleaned
    if broker_name is not None:
        cleaned = broker_name.strip()
        if not cleaned:
            raise BrokerFeeError("INVALID_BROKER_NAME", "Укажите название брокера")
        profile.broker_name = cleaned
    if tariff_name is not None:
        profile.tariff_name = tariff_name.strip() or profile.tariff_name
    profile.updated_at = datetime.now(UTC)

    if buy_rate_pct is not None or sell_rate_pct is not None:
        buy_rate = _pct_to_rate(buy_rate_pct) if buy_rate_pct is not None else None
        sell_rate = _pct_to_rate(sell_rate_pct) if sell_rate_pct is not None else None
        for rule in profile.rules:
            side = (rule.side or "").upper()
            if buy_rate is not None and side == "BUY":
                rule.percentage_rate = buy_rate
                rule.explanation = f"Custom BUY rate {buy_rate_pct}% of clean notional"
            if sell_rate is not None and side == "SELL":
                rule.percentage_rate = sell_rate
                rule.explanation = f"Custom SELL rate {sell_rate_pct}% of clean notional"

    session.flush()
    return profile


def estimate_fee_for_portfolio(
    session: Session,
    *,
    portfolio: ManualPortfolio,
    side: str,
    notional: Decimal,
    instrument_id: int | None = None,
    instrument_symbol: str | None = None,
    as_of: date | None = None,
    nkd: Decimal = ZERO,
) -> dict[str, Any]:
    """Preview estimate for UI / Decision. Never invents a fake zero when UNKNOWN."""
    as_of_d = as_of or datetime.now(UTC).date()
    side_u = (side or "").strip().upper()
    if side_u not in {"BUY", "SELL"}:
        raise BrokerFeeError("INVALID_SIDE", "side must be BUY or SELL")

    symbol = (instrument_symbol or "").strip().upper() or None
    asset_class: str | None = None
    if instrument_id is not None:
        inst = session.get(Instrument, int(instrument_id))
        if inst is None:
            raise BrokerFeeError("INSTRUMENT_NOT_FOUND", "Инструмент не найден", http_status=404)
        symbol = symbol or (inst.symbol or "").upper() or None
        asset_class = (inst.asset_class or "").upper() or None

    if portfolio.broker_account_id is None:
        return {
            "status": FeeStatus.UNKNOWN,
            "amount": None,
            "fee_rule_id": None,
            "explanation": "Portfolio has no broker account assigned",
            "commission_source": "NONE",
            "broker_account_id": None,
            "limitation": "BROKER_FEE_PROFILE_MISSING",
            "matched_rule_code": None,
            "exclude_from_turnover": False,
        }

    account = get_broker_account(session, int(portfolio.broker_account_id))
    engine = load_fee_engine(session, int(account.fee_profile_id))
    day_to = broker_account_day_turnover(
        session, broker_account_id=int(account.id), as_of=as_of_d
    )
    estimate = engine.estimate_fee(
        FeeEstimateContext(
            as_of=as_of_d,
            side=side_u,
            notional=money(notional),
            nkd=money(nkd),
            market="MOEX",
            execution_channel="ONLINE",
            asset_class=asset_class,
            instrument_id=int(instrument_id) if instrument_id is not None else None,
            instrument_symbol=symbol,
            broker_account_day_turnover=day_to,
        )
    )
    return {
        "status": estimate.status,
        "amount": str(estimate.amount) if estimate.amount is not None else None,
        "fee_rule_id": estimate.fee_rule_id,
        "explanation": estimate.explanation,
        "commission_source": "PROFILE_ESTIMATE" if estimate.status == FeeStatus.KNOWN else "NONE",
        "broker_account_id": int(account.id),
        "limitation": None if estimate.status == FeeStatus.KNOWN else "FEE_RULE_UNMATCHED",
        "matched_rule_code": estimate.matched_rule_code,
        "exclude_from_turnover": bool(estimate.exclude_from_turnover),
        "broker_account_day_turnover": str(day_to),
    }


def resolve_operation_commission(
    session: Session,
    *,
    portfolio: ManualPortfolio,
    operation_type: str,
    commission: Decimal | None,
    commission_provided: bool,
    units: Decimal | None,
    price: Decimal | None,
    amount: Decimal | None,
    instrument_id: int | None,
    occurred_at: datetime,
) -> tuple[Decimal, CommissionSource, int | None, int | None]:
    """MANUAL > PROFILE_ESTIMATE > NONE. Returns (amount, source, broker_account_id, fee_rule_id)."""
    op = (operation_type or "").upper()
    broker_id = int(portfolio.broker_account_id) if portfolio.broker_account_id is not None else None

    # Explicit amount (including 0) is always MANUAL. API sets commission_provided via
    # model_fields_set; legacy/internal callers often pass commission=Decimal(...) only.
    if commission_provided or commission is not None:
        return money(commission or ZERO), "MANUAL", broker_id, None

    if op not in {"BUY", "SELL"}:
        return ZERO, "NONE", broker_id, None

    if broker_id is None:
        return ZERO, "NONE", None, None

    notional = ZERO
    if units is not None and price is not None:
        notional = money(_d(units) * _d(price))
    elif amount is not None:
        notional = money(amount)
    if notional <= ZERO:
        return ZERO, "NONE", broker_id, None

    preview = estimate_fee_for_portfolio(
        session,
        portfolio=portfolio,
        side=op,
        notional=notional,
        instrument_id=instrument_id,
        as_of=occurred_at.astimezone(UTC).date(),
    )
    if preview["status"] != FeeStatus.KNOWN or preview["amount"] is None:
        return ZERO, "NONE", broker_id, None
    return money(preview["amount"]), "PROFILE_ESTIMATE", broker_id, preview.get("fee_rule_id")


def estimate_fee_amount(
    session: Session,
    *,
    portfolio: ManualPortfolio,
    side: str,
    notional: Decimal,
    instrument_id: int | None = None,
    instrument_symbol: str | None = None,
    as_of: date | None = None,
) -> FeeEstimate | None:
    """Domain FeeEstimate for Decision lot planning; None if no broker / unknown."""
    if portfolio.broker_account_id is None:
        return None
    preview = estimate_fee_for_portfolio(
        session,
        portfolio=portfolio,
        side=side,
        notional=notional,
        instrument_id=instrument_id,
        instrument_symbol=instrument_symbol,
        as_of=as_of,
    )
    if preview["status"] != FeeStatus.KNOWN:
        return FeeEstimate(
            status=FeeStatus.UNKNOWN,
            amount=None,
            fee_rule_id=None,
            explanation=str(preview.get("explanation") or "unknown"),
            exclude_from_turnover=False,
            matched_rule_code=None,
        )
    return FeeEstimate(
        status=FeeStatus.KNOWN,
        amount=money(preview["amount"]),
        fee_rule_id=preview.get("fee_rule_id"),
        explanation=str(preview.get("explanation") or ""),
        exclude_from_turnover=bool(preview.get("exclude_from_turnover")),
        matched_rule_code=preview.get("matched_rule_code"),
    )
