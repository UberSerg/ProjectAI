"""Personal Portfolio V1 — journal apply, projection, valuation, reconciliation."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.infrastructure.market.models import Instrument
from app.modules.investment.application.equity_lot_size import resolve_equity_lot_sizes
from app.modules.investment.infrastructure.models import BondTerm
from app.modules.portfolio.domain.lots import LotValidationError, assert_lot_compatible
from app.modules.portfolio.domain.personal_ledger import (
    ZERO,
    LedgerError,
    LedgerEvent,
    LedgerState,
    OperationType,
    apply_event,
    investment_pnl,
    lots_to_units,
    money,
    units_q,
)
from app.modules.portfolio.domain.valuation import latest_eod_close, value_position
from app.modules.portfolio.infrastructure.models import (
    ManualPortfolio,
    ManualPosition,
    PersonalOperation,
)

PRIMARY_NAME = "Основной портфель"
TEST_NAME_PREFIX = "TEST — "


class PersonalPortfolioError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _d(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def get_or_create_primary(session: Session) -> ManualPortfolio:
    row = session.scalar(
        select(ManualPortfolio)
        .options(selectinload(ManualPortfolio.positions))
        .where(ManualPortfolio.is_test.is_(False))
        .order_by(ManualPortfolio.id.asc())
        .limit(1)
    )
    if row is not None:
        if row.name == "Primary Manual Portfolio":
            row.name = PRIMARY_NAME
        return row
    row = ManualPortfolio(
        name=PRIMARY_NAME,
        source="MANUAL",
        base_currency="RUB",
        cash_rub=ZERO,
        status="ACTIVE",
        is_test=False,
        version=1,
    )
    session.add(row)
    session.flush()
    return row


def get_or_create_test_portfolio(session: Session, *, name: str | None = None) -> ManualPortfolio:
    label = name or f"{TEST_NAME_PREFIX}Personal Portfolio V1"
    row = session.scalar(
        select(ManualPortfolio)
        .options(selectinload(ManualPortfolio.positions))
        .where(ManualPortfolio.is_test.is_(True), ManualPortfolio.name == label)
        .order_by(ManualPortfolio.id.asc())
        .limit(1)
    )
    if row is not None:
        return row
    row = ManualPortfolio(
        name=label,
        source="MANUAL",
        base_currency="RUB",
        cash_rub=ZERO,
        status="ACTIVE",
        is_test=True,
        note="Isolated test portfolio — not the owner's real book",
        version=1,
    )
    session.add(row)
    session.flush()
    return row


def _active_operations(session: Session, portfolio_id: int) -> list[PersonalOperation]:
    return list(
        session.scalars(
            select(PersonalOperation)
            .where(
                PersonalOperation.portfolio_id == portfolio_id,
                PersonalOperation.status == "ACTIVE",
            )
            .order_by(PersonalOperation.occurred_at.asc(), PersonalOperation.id.asc())
        ).all()
    )


def rebuild_ledger_from_journal(session: Session, portfolio_id: int) -> LedgerState:
    state = LedgerState()
    for op in _active_operations(session, portfolio_id):
        state = apply_event(
            state,
            LedgerEvent(
                operation_type=OperationType(op.operation_type),
                instrument_id=op.instrument_id,
                units=_d(op.units or ZERO),
                price=_d(op.price or ZERO),
                amount=_d(op.amount or ZERO),
                commission=_d(op.commission or ZERO),
            ),
        )
    return state


def project_portfolio(session: Session, portfolio: ManualPortfolio, state: LedgerState) -> None:
    """Write derived cash/positions/totals onto the portfolio row."""
    portfolio.cash_rub = money(state.cash)
    portfolio.total_contributed_rub = money(state.contributed)
    portfolio.total_withdrawn_rub = money(state.withdrawn)
    portfolio.realized_pnl_rub = money(state.realized_pnl)
    portfolio.updated_at = datetime.now(UTC)
    portfolio.version = int(portfolio.version or 1) + 1

    existing = {
        int(p.instrument_id): p
        for p in session.scalars(
            select(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id)
        ).all()
    }
    keep: set[int] = set()
    for instrument_id, book in state.positions.items():
        keep.add(instrument_id)
        row = existing.get(instrument_id)
        if row is None:
            row = ManualPosition(
                portfolio_id=portfolio.id,
                instrument_id=instrument_id,
                units=book.units,
                average_price=book.average_cost,
            )
            session.add(row)
        else:
            row.units = book.units
            row.average_price = book.average_cost
            row.updated_at = datetime.now(UTC)
    for instrument_id, row in existing.items():
        if instrument_id not in keep:
            session.delete(row)
    session.flush()


def _resolve_lot_size(session: Session, instrument: Instrument) -> int | None:
    if (instrument.asset_class or "").lower() == "bond":
        term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument.id))
        if term is None or term.lot_size is None:
            return None
        return int(term.lot_size)
    lots = resolve_equity_lot_sizes(session, [instrument], fetch_missing=False)
    res = lots.get(int(instrument.id))
    return res.lot_size if res else None


def _parse_occurred_at(value: datetime | date | str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    text = str(value).strip()
    if len(text) == 10 and text[4] == "-":
        y, m, d = (int(x) for x in text.split("-"))
        return datetime(y, m, d, tzinfo=UTC)
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def create_operation(
    session: Session,
    *,
    portfolio: ManualPortfolio,
    operation_type: str,
    occurred_at: datetime | date | str,
    idempotency_key: str | None = None,
    instrument_id: int | None = None,
    lots: Decimal | None = None,
    units: Decimal | None = None,
    price: Decimal | None = None,
    amount: Decimal | None = None,
    commission: Decimal | None = None,
    note: str | None = None,
    non_standard_lot: bool = False,
    supersedes_operation_id: int | None = None,
    correction_reason: str | None = None,
) -> PersonalOperation:
    key = (idempotency_key or "").strip() or str(uuid4())
    existing = session.scalar(
        select(PersonalOperation).where(
            PersonalOperation.portfolio_id == portfolio.id,
            PersonalOperation.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing

    try:
        op_type = OperationType(operation_type)
    except ValueError as exc:
        raise PersonalPortfolioError("UNSUPPORTED_OPERATION", "Неизвестный тип операции") from exc

    resolved_units = units_q(units) if units is not None else ZERO
    resolved_lots = _d(lots) if lots is not None else None
    instrument: Instrument | None = None
    if instrument_id is not None:
        instrument = session.get(Instrument, instrument_id)
        if instrument is None:
            raise PersonalPortfolioError("INSTRUMENT_NOT_FOUND", "Инструмент не найден", http_status=404)

    if op_type in (OperationType.BUY, OperationType.SELL, OperationType.OPENING_POSITION):
        if instrument is None:
            raise PersonalPortfolioError("INSTRUMENT_REQUIRED", "Нужно указать инструмент")
        lot_size = _resolve_lot_size(session, instrument)
        if resolved_lots is not None and resolved_lots > ZERO:
            if lot_size is None:
                raise PersonalPortfolioError(
                    "LOT_SIZE_UNKNOWN",
                    "Размер лота неизвестен — укажите количество штук или дождитесь LOTSIZE",
                )
            resolved_units = lots_to_units(resolved_lots, lot_size)
        if resolved_units <= ZERO:
            raise PersonalPortfolioError("INVALID_UNITS", "Количество бумаг должно быть больше нуля")
        try:
            assert_lot_compatible(resolved_units, lot_size, non_standard_lot=non_standard_lot)
        except LotValidationError as exc:
            raise PersonalPortfolioError(exc.code, str(exc)) from exc

    if supersedes_operation_id is not None:
        old = session.get(PersonalOperation, supersedes_operation_id)
        if old is None or old.portfolio_id != portfolio.id:
            raise PersonalPortfolioError("OPERATION_NOT_FOUND", "Исходная операция не найдена", http_status=404)
        if old.status != "ACTIVE":
            raise PersonalPortfolioError("OPERATION_NOT_ACTIVE", "Исправлять можно только активную операцию")
        old.status = "SUPERSEDED"
        old.correction_reason = correction_reason or old.correction_reason

    row = PersonalOperation(
        portfolio_id=portfolio.id,
        operation_type=op_type.value,
        status="ACTIVE",
        occurred_at=_parse_occurred_at(occurred_at),
        instrument_id=instrument_id,
        lots=resolved_lots,
        units=resolved_units if resolved_units > ZERO else None,
        price=money(price) if price is not None else None,
        amount=money(amount) if amount is not None else None,
        commission=money(commission or ZERO),
        currency="RUB",
        source="MANUAL",
        note=note,
        idempotency_key=key,
        supersedes_operation_id=supersedes_operation_id,
        correction_reason=correction_reason,
    )
    session.add(row)
    session.flush()

    try:
        state = rebuild_ledger_from_journal(session, portfolio.id)
    except LedgerError as exc:
        session.delete(row)
        if supersedes_operation_id is not None:
            old = session.get(PersonalOperation, supersedes_operation_id)
            if old is not None:
                old.status = "ACTIVE"
        session.flush()
        raise PersonalPortfolioError(exc.code, exc.message) from exc

    project_portfolio(session, portfolio, state)
    return row


def cancel_operation(
    session: Session,
    *,
    portfolio: ManualPortfolio,
    operation_id: int,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> PersonalOperation:
    """Soft-cancel: mark SUPERSEDED/CANCELLED and reproject (no replacement)."""
    key = (idempotency_key or "").strip() or f"cancel:{operation_id}:{uuid4()}"
    existing = session.scalar(
        select(PersonalOperation).where(
            PersonalOperation.portfolio_id == portfolio.id,
            PersonalOperation.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing

    op = session.get(PersonalOperation, operation_id)
    if op is None or op.portfolio_id != portfolio.id:
        raise PersonalPortfolioError("OPERATION_NOT_FOUND", "Операция не найдена", http_status=404)
    if op.status != "ACTIVE":
        raise PersonalPortfolioError("OPERATION_NOT_ACTIVE", "Операция уже не активна")
    op.status = "CANCELLED"
    op.correction_reason = reason
    # Marker row for idempotent cancel requests
    marker = PersonalOperation(
        portfolio_id=portfolio.id,
        operation_type=op.operation_type,
        status="CANCELLED",
        occurred_at=op.occurred_at,
        instrument_id=op.instrument_id,
        lots=op.lots,
        units=op.units,
        price=op.price,
        amount=op.amount,
        commission=op.commission,
        currency=op.currency,
        source="MANUAL",
        note=f"CANCEL of #{op.id}",
        idempotency_key=key,
        supersedes_operation_id=op.id,
        correction_reason=reason,
    )
    session.add(marker)
    session.flush()
    state = rebuild_ledger_from_journal(session, portfolio.id)
    project_portfolio(session, portfolio, state)
    return op


def reconcile(session: Session, portfolio: ManualPortfolio) -> dict[str, Any]:
    state = rebuild_ledger_from_journal(session, portfolio.id)
    cash_ok = money(portfolio.cash_rub) == money(state.cash)
    contributed_ok = money(portfolio.total_contributed_rub or ZERO) == money(state.contributed)
    withdrawn_ok = money(portfolio.total_withdrawn_rub or ZERO) == money(state.withdrawn)
    realized_ok = money(portfolio.realized_pnl_rub or ZERO) == money(state.realized_pnl)

    projected = {
        int(p.instrument_id): (units_q(p.units), money(p.average_price or ZERO))
        for p in session.scalars(
            select(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id)
        ).all()
    }
    ledger_pos = {
        iid: (units_q(book.units), money(book.average_cost)) for iid, book in state.positions.items()
    }
    positions_ok = projected == ledger_pos
    ok = cash_ok and contributed_ok and withdrawn_ok and realized_ok and positions_ok
    return {
        "status": "OK" if ok else "MISMATCH",
        "cash_ok": cash_ok,
        "contributed_ok": contributed_ok,
        "withdrawn_ok": withdrawn_ok,
        "realized_ok": realized_ok,
        "positions_ok": positions_ok,
        "ledger_cash": str(money(state.cash)),
        "projected_cash": str(money(portfolio.cash_rub)),
        "ledger_positions": {
            str(k): {"units": str(v[0]), "average_cost": str(v[1])} for k, v in ledger_pos.items()
        },
        "projected_positions": {
            str(k): {"units": str(v[0]), "average_cost": str(v[1])} for k, v in projected.items()
        },
    }


def _operation_to_dict(op: PersonalOperation, *, owner: bool) -> dict[str, Any]:
    base = {
        "id": op.id,
        "operation_type": op.operation_type,
        "status": op.status,
        "occurred_at": op.occurred_at.isoformat() if op.occurred_at else None,
        "instrument_id": op.instrument_id,
        "lots": str(op.lots) if op.lots is not None else None,
        "units": str(op.units) if op.units is not None else None,
        "price": str(op.price) if op.price is not None else None,
        "amount": str(op.amount) if op.amount is not None else None,
        "commission": str(op.commission),
        "currency": op.currency,
        "note": op.note,
        "created_at": op.created_at.isoformat() if op.created_at else None,
    }
    if owner:
        base.update(
            {
                "source": op.source,
                "idempotency_key": op.idempotency_key,
                "supersedes_operation_id": op.supersedes_operation_id,
                "correction_reason": op.correction_reason,
            }
        )
    return base


def get_personal_summary(session: Session, portfolio: ManualPortfolio, *, owner: bool = False) -> dict[str, Any]:
    positions_out: list[dict[str, Any]] = []
    securities_mv = ZERO
    missing_prices = 0
    price_dates: list[str] = []
    for pos in session.scalars(
        select(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id)
    ).all():
        instrument = session.get(Instrument, pos.instrument_id)
        if instrument is None:
            missing_prices += 1
            positions_out.append(
                {
                    "instrument_id": pos.instrument_id,
                    "secid": None,
                    "name": None,
                    "units": str(pos.units),
                    "lots": None,
                    "average_price": str(pos.average_price) if pos.average_price is not None else None,
                    "current_price": None,
                    "price_date": None,
                    "market_value": None,
                    "unrealized_pnl": None,
                    "price_available": False,
                }
            )
            continue
        lot_size = _resolve_lot_size(session, instrument)
        lots_display = None
        if lot_size and lot_size > 0:
            lots_display = str(units_q(pos.units) / Decimal(lot_size))
        val = value_position(session, instrument, _d(pos.units))
        # Prefer EOD for "Оценка по ценам на …" freshness
        eod_px, eod_ts = latest_eod_close(session, int(instrument.id))
        unit_price = eod_px if eod_px is not None else val.unit_price
        price_date = None
        if eod_ts:
            price_date = eod_ts[:10]
            price_dates.append(price_date)
        market_value = None
        unrealized = None
        if unit_price is not None:
            market_value = money(_d(pos.units) * unit_price)
            securities_mv = money(securities_mv + market_value)
            if pos.average_price is not None:
                unrealized = money(market_value - money(_d(pos.units) * _d(pos.average_price)))
        else:
            missing_prices += 1
        positions_out.append(
            {
                "instrument_id": instrument.id,
                "secid": instrument.symbol,
                "name": instrument.name or instrument.symbol,
                "units": str(pos.units),
                "lots": lots_display,
                "lot_size": lot_size,
                "average_price": str(pos.average_price) if pos.average_price is not None else None,
                "current_price": str(money(unit_price)) if unit_price is not None else None,
                "price_date": price_date,
                "market_value": str(market_value) if market_value is not None else None,
                "unrealized_pnl": str(unrealized) if unrealized is not None else None,
                "price_available": unit_price is not None,
                "price_label": None if unit_price is not None else "Цена недоступна",
            }
        )

    cash = money(portfolio.cash_rub)
    contributed = money(portfolio.total_contributed_rub or ZERO)
    withdrawn = money(portfolio.total_withdrawn_rub or ZERO)
    valuation_complete = missing_prices == 0
    nav = money(cash + securities_mv) if True else None
    # When prices missing, NAV is partial (cash + known MV only)
    inv_pnl = investment_pnl(nav=nav, contributed=contributed, withdrawn=withdrawn)
    as_of = max(price_dates) if price_dates else None

    ops = list(
        session.scalars(
            select(PersonalOperation)
            .where(PersonalOperation.portfolio_id == portfolio.id)
            .order_by(PersonalOperation.occurred_at.desc(), PersonalOperation.id.desc())
            .limit(50)
        ).all()
    )

    payload: dict[str, Any] = {
        "portfolio": {
            "id": portfolio.id,
            "name": portfolio.name,
            "base_currency": portfolio.base_currency,
            "status": portfolio.status,
            "is_test": bool(portfolio.is_test),
            "note": portfolio.note,
            "version": portfolio.version,
            "has_operations": len(ops) > 0 or bool(session.scalar(
                select(PersonalOperation.id)
                .where(PersonalOperation.portfolio_id == portfolio.id)
                .limit(1)
            )),
        },
        "summary": {
            "cash_rub": str(cash),
            "securities_value_rub": str(securities_mv),
            "nav_rub": str(nav),
            "contributed_rub": str(contributed),
            "withdrawn_rub": str(withdrawn),
            "investment_pnl_rub": str(inv_pnl),
            "realized_pnl_rub": str(money(portfolio.realized_pnl_rub or ZERO)),
            "valuation_complete": valuation_complete,
            "valuation_partial": not valuation_complete,
            "valuation_as_of": as_of,
            "valuation_label": (
                f"Оценка по ценам на {as_of[8:10]}.{as_of[5:7]}.{as_of[0:4]}"
                if as_of
                else "Оценка недоступна — нет цен"
            ),
            "missing_price_count": missing_prices,
        },
        "positions": positions_out,
        "operations": [_operation_to_dict(o, owner=owner) for o in ops],
        "recommendation_disclaimer": "Модельная рекомендация",
    }
    if owner:
        payload["reconciliation"] = reconcile(session, portfolio)
    return payload
