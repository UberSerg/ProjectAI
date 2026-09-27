"""Personal Portfolio V1 — journal apply, projection, valuation, reconciliation."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
LEGACY_BOOTSTRAP_SOURCE = "LEGACY_BOOTSTRAP"
JOURNAL_MANAGED_MESSAGE = (
    "Этот портфель уже ведётся через журнал операций. "
    "Добавьте покупку, продажу, пополнение или корректировку через «Добавить операцию»."
)
BOND_TRADE_MESSAGE = (
    "Операции с облигациями пока нельзя вносить через обычную цену: "
    "биржевая цена облигации указывается в процентах от номинала. "
    "Kraken не будет считать её рублёвой ценой."
)


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


def journal_operation_count(session: Session, portfolio_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(PersonalOperation)
            .where(PersonalOperation.portfolio_id == portfolio_id)
        )
        or 0
    )


def is_journal_managed(session: Session, portfolio_id: int) -> bool:
    return journal_operation_count(session, portfolio_id) > 0


def assert_legacy_writes_allowed(session: Session, portfolio: ManualPortfolio) -> None:
    if is_journal_managed(session, int(portfolio.id)):
        raise PersonalPortfolioError(
            "PORTFOLIO_JOURNAL_MANAGED",
            JOURNAL_MANAGED_MESSAGE,
            http_status=409,
        )


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


def _fmt_ru_date(iso_yyyy_mm_dd: str) -> str:
    return f"{iso_yyyy_mm_dd[8:10]}.{iso_yyyy_mm_dd[5:7]}.{iso_yyyy_mm_dd[0:4]}"


def _valuation_label(
    *,
    price_dates: list[str],
    missing_prices: int,
) -> str:
    if not price_dates and missing_prices > 0:
        return "Частичная оценка · для части позиций цена недоступна"
    if not price_dates:
        return "Оценка недоступна — нет цен"
    earliest = min(price_dates)
    latest = max(price_dates)
    if earliest == latest:
        range_part = f"цены на {_fmt_ru_date(earliest)}"
        complete = f"Оценка по ценам на {_fmt_ru_date(earliest)}"
    else:
        range_part = f"цены {_fmt_ru_date(earliest)}–{_fmt_ru_date(latest)}"
        complete = f"Цены по позициям: {_fmt_ru_date(earliest)}–{_fmt_ru_date(latest)}"
    if missing_prices <= 0:
        return complete
    noun = "позиции" if missing_prices == 1 else "позиций"
    return f"Частичная оценка · {range_part} · для {missing_prices} {noun} цена недоступна"


def _normalize_money_str(value: object | None) -> str | None:
    if value is None:
        return None
    return str(money(value))


def _normalize_units_str(value: object | None) -> str | None:
    if value is None:
        return None
    return str(units_q(value))


def _idempotency_fingerprint(
    *,
    operation_type: str,
    occurred_at: datetime,
    instrument_id: int | None,
    units: Decimal | None,
    lots: Decimal | None,
    price: Decimal | None,
    amount: Decimal | None,
    commission: Decimal | None,
    note: str | None,
    supersedes_operation_id: int | None,
) -> dict[str, Any]:
    return {
        "operation_type": operation_type,
        "occurred_at": occurred_at.astimezone(UTC).date().isoformat(),
        "instrument_id": instrument_id,
        "units": _normalize_units_str(units) if units is not None and units > ZERO else None,
        "lots": _normalize_units_str(lots) if lots is not None else None,
        "price": _normalize_money_str(price) if price is not None else None,
        "amount": _normalize_money_str(amount) if amount is not None else None,
        "commission": _normalize_money_str(commission or ZERO),
        "note": (note or "").strip() or None,
        "supersedes_operation_id": supersedes_operation_id,
    }


def _operation_fingerprint(op: PersonalOperation) -> dict[str, Any]:
    return _idempotency_fingerprint(
        operation_type=op.operation_type,
        occurred_at=op.occurred_at,
        instrument_id=op.instrument_id,
        units=_d(op.units) if op.units is not None else None,
        lots=_d(op.lots) if op.lots is not None else None,
        price=_d(op.price) if op.price is not None else None,
        amount=_d(op.amount) if op.amount is not None else None,
        commission=_d(op.commission or ZERO),
        note=op.note,
        supersedes_operation_id=op.supersedes_operation_id,
    )


def _assert_idempotency_match(existing: PersonalOperation, expected: dict[str, Any]) -> None:
    if _operation_fingerprint(existing) != expected:
        raise PersonalPortfolioError(
            "IDEMPOTENCY_KEY_REUSED",
            "Этот идентификатор операции уже использован для других данных.",
            http_status=409,
        )


def _legacy_positions(session: Session, portfolio_id: int) -> list[ManualPosition]:
    return list(
        session.scalars(
            select(ManualPosition).where(ManualPosition.portfolio_id == portfolio_id)
        ).all()
    )


def _needs_legacy_bootstrap(session: Session, portfolio: ManualPortfolio) -> bool:
    if journal_operation_count(session, int(portfolio.id)) > 0:
        return False
    cash = money(portfolio.cash_rub)
    positions = _legacy_positions(session, int(portfolio.id))
    return cash != ZERO or len(positions) > 0


def ensure_legacy_bootstrap(session: Session, portfolio: ManualPortfolio) -> None:
    """One-time deterministic transition: legacy Manual state → opening journal rows."""
    if not _needs_legacy_bootstrap(session, portfolio):
        return

    positions = _legacy_positions(session, int(portfolio.id))
    missing_cost = [p for p in positions if p.average_price is None]
    if missing_cost:
        labels = ", ".join(str(p.instrument_id) for p in missing_cost)
        raise PersonalPortfolioError(
            "LEGACY_COST_BASIS_REQUIRED",
            (
                "Перед активацией журнала укажите себестоимость для позиций без average_price "
                f"(instrument_id: {labels}). Нулевая себестоимость не подставляется."
            ),
            http_status=409,
        )

    bootstrap_at = datetime.now(UTC)
    cash = money(portfolio.cash_rub)
    if cash > ZERO:
        key = f"legacy-bootstrap:{portfolio.id}:cash"
        if (
            session.scalar(
                select(PersonalOperation.id).where(
                    PersonalOperation.portfolio_id == portfolio.id,
                    PersonalOperation.idempotency_key == key,
                )
            )
            is None
        ):
            session.add(
                PersonalOperation(
                    portfolio_id=portfolio.id,
                    operation_type=OperationType.OPENING_CASH.value,
                    status="ACTIVE",
                    occurred_at=bootstrap_at,
                    amount=cash,
                    commission=ZERO,
                    currency="RUB",
                    source=LEGACY_BOOTSTRAP_SOURCE,
                    note="Legacy Manual cash bootstrap",
                    idempotency_key=key,
                )
            )

    for pos in positions:
        key = f"legacy-bootstrap:{portfolio.id}:position:{pos.id}"
        if (
            session.scalar(
                select(PersonalOperation.id).where(
                    PersonalOperation.portfolio_id == portfolio.id,
                    PersonalOperation.idempotency_key == key,
                )
            )
            is not None
        ):
            continue
        # Bonds may exist in legacy Manual; opening uses known RUB average_price only.
        instrument = session.get(Instrument, pos.instrument_id)
        if instrument is not None and (instrument.asset_class or "").lower() == "bond":
            raise PersonalPortfolioError(
                "BOND_TRADE_ACCOUNTING_NOT_READY",
                BOND_TRADE_MESSAGE
                + " Сначала перенесите облигации отдельным контрактом учёта.",
                http_status=409,
            )
        session.add(
            PersonalOperation(
                portfolio_id=portfolio.id,
                operation_type=OperationType.OPENING_POSITION.value,
                status="ACTIVE",
                occurred_at=bootstrap_at,
                instrument_id=int(pos.instrument_id),
                units=units_q(pos.units),
                price=money(pos.average_price),
                commission=ZERO,
                currency="RUB",
                source=LEGACY_BOOTSTRAP_SOURCE,
                note=f"Legacy Manual position bootstrap #{pos.id}",
                idempotency_key=key,
            )
        )
    session.flush()


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

    try:
        op_type = OperationType(operation_type)
    except ValueError as exc:
        raise PersonalPortfolioError("UNSUPPORTED_OPERATION", "Неизвестный тип операции") from exc

    occurred_dt = _parse_occurred_at(occurred_at)
    today = datetime.now(UTC).date()
    if occurred_dt.astimezone(UTC).date() > today:
        raise PersonalPortfolioError(
            "FUTURE_DATED_OPERATION",
            "Операцию нельзя датировать будущим днём — она сразу меняет текущее состояние портфеля.",
        )

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
        if (instrument.asset_class or "").lower() == "bond":
            raise PersonalPortfolioError(
                "BOND_TRADE_ACCOUNTING_NOT_READY",
                BOND_TRADE_MESSAGE,
                http_status=409,
            )
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

    fingerprint = _idempotency_fingerprint(
        operation_type=op_type.value,
        occurred_at=occurred_dt,
        instrument_id=instrument_id,
        units=resolved_units if resolved_units > ZERO else None,
        lots=resolved_lots,
        price=price,
        amount=amount,
        commission=commission,
        note=note,
        supersedes_operation_id=supersedes_operation_id,
    )
    if existing is not None:
        _assert_idempotency_match(existing, fingerprint)
        return existing

    # All mutations in a savepoint: invalid ledger apply must not leave half-state
    # (caught PersonalPortfolioError must not commit a bad ACTIVE journal row).
    try:
        with session.begin_nested():
            ensure_legacy_bootstrap(session, portfolio)

            if supersedes_operation_id is not None:
                old = session.get(PersonalOperation, supersedes_operation_id)
                if old is None or old.portfolio_id != portfolio.id:
                    raise PersonalPortfolioError(
                        "OPERATION_NOT_FOUND", "Исходная операция не найдена", http_status=404
                    )
                if old.status != "ACTIVE":
                    raise PersonalPortfolioError(
                        "OPERATION_NOT_ACTIVE", "Исправлять можно только активную операцию"
                    )
                old.status = "SUPERSEDED"
                old.correction_reason = correction_reason or old.correction_reason

            row = PersonalOperation(
                portfolio_id=portfolio.id,
                operation_type=op_type.value,
                status="ACTIVE",
                occurred_at=occurred_dt,
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
                raise PersonalPortfolioError(exc.code, exc.message) from exc
            project_portfolio(session, portfolio, state)
            return row
    except IntegrityError as exc:
        raced = session.scalar(
            select(PersonalOperation).where(
                PersonalOperation.portfolio_id == portfolio.id,
                PersonalOperation.idempotency_key == key,
            )
        )
        if raced is None:
            raise PersonalPortfolioError(
                "IDEMPOTENCY_CONFLICT",
                "Конфликт идентификатора операции. Повторите запрос.",
                http_status=409,
            ) from exc
        _assert_idempotency_match(raced, fingerprint)
        return raced


def cancel_operation(
    session: Session,
    *,
    portfolio: ManualPortfolio,
    operation_id: int,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> PersonalOperation:
    """Soft-cancel: mark CANCELLED and reproject (no replacement). Returns original op."""
    key = (idempotency_key or "").strip() or f"cancel:{operation_id}:{uuid4()}"
    existing = session.scalar(
        select(PersonalOperation).where(
            PersonalOperation.portfolio_id == portfolio.id,
            PersonalOperation.idempotency_key == key,
        )
    )
    if existing is not None:
        # Marker rows supersede the cancelled operation — always return the original.
        if existing.supersedes_operation_id is not None:
            original = session.get(PersonalOperation, existing.supersedes_operation_id)
            if original is not None:
                return original
        return existing

    op = session.get(PersonalOperation, operation_id)
    if op is None or op.portfolio_id != portfolio.id:
        raise PersonalPortfolioError("OPERATION_NOT_FOUND", "Операция не найдена", http_status=404)
    if op.status != "ACTIVE":
        raise PersonalPortfolioError("OPERATION_NOT_ACTIVE", "Операция уже не активна")
    op.status = "CANCELLED"
    op.correction_reason = reason
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
    try:
        with session.begin_nested():
            session.add(marker)
            session.flush()
    except IntegrityError:
        raced = session.scalar(
            select(PersonalOperation).where(
                PersonalOperation.portfolio_id == portfolio.id,
                PersonalOperation.idempotency_key == key,
            )
        )
        if raced is not None and raced.supersedes_operation_id is not None:
            original = session.get(PersonalOperation, raced.supersedes_operation_id)
            if original is not None:
                return original
        raise
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


def _personal_mark(
    session: Session,
    instrument: Instrument,
    units: Decimal,
) -> tuple[Decimal | None, Decimal | None, str | None, str | None]:
    """Return (unit_price, market_value, price_date, asset_hint).

    Equity/fund: latest valid EOD only (no intraday fallback).
    Bond: existing dirty valuation (never treat clean % as RUB).
    """
    asset = (instrument.asset_class or "").lower()
    if asset == "bond":
        val = value_position(session, instrument, units)
        if val.market_value is None or val.unit_price is None:
            return None, None, None, "bond"
        as_of = val.detail.get("as_of") if isinstance(val.detail, dict) else None
        price_date = str(as_of)[:10] if as_of else None
        return money(val.unit_price), money(val.market_value), price_date, "bond"

    if asset in {"equity", "fund", ""}:
        eod_px, eod_ts = latest_eod_close(session, int(instrument.id))
        if eod_px is None:
            return None, None, None, asset or "equity"
        price_date = eod_ts[:10] if eod_ts else None
        mv = money(units * eod_px)
        return money(eod_px), mv, price_date, asset or "equity"

    # Unsupported for Personal Portfolio mark
    return None, None, None, asset


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
                    "price_label": "Цена недоступна",
                }
            )
            continue
        lot_size = _resolve_lot_size(session, instrument)
        lots_display = None
        if lot_size and lot_size > 0:
            lots_display = str(units_q(pos.units) / Decimal(lot_size))
        unit_price, market_value, price_date, _asset = _personal_mark(
            session, instrument, _d(pos.units)
        )
        unrealized = None
        if unit_price is not None and market_value is not None:
            securities_mv = money(securities_mv + market_value)
            if price_date:
                price_dates.append(price_date)
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
    known_nav = money(cash + securities_mv)
    # Partial valuation: never treat unknown holdings as zero for total investment P&L.
    if valuation_complete:
        inv_pnl: Decimal | None = investment_pnl(
            nav=known_nav, contributed=contributed, withdrawn=withdrawn
        )
    else:
        inv_pnl = None
    as_of_from = min(price_dates) if price_dates else None
    as_of_to = max(price_dates) if price_dates else None

    ops = list(
        session.scalars(
            select(PersonalOperation)
            .where(PersonalOperation.portfolio_id == portfolio.id)
            .order_by(PersonalOperation.occurred_at.desc(), PersonalOperation.id.desc())
            .limit(50)
        ).all()
    )
    has_ops = journal_operation_count(session, int(portfolio.id)) > 0

    payload: dict[str, Any] = {
        "portfolio": {
            "id": portfolio.id,
            "name": portfolio.name,
            "base_currency": portfolio.base_currency,
            "status": portfolio.status,
            "is_test": bool(portfolio.is_test),
            "note": portfolio.note,
            "version": portfolio.version,
            "has_operations": has_ops,
        },
        "summary": {
            "cash_rub": str(cash),
            "securities_value_rub": str(securities_mv),
            "nav_rub": str(known_nav),
            "known_nav_rub": str(known_nav),
            "contributed_rub": str(contributed),
            "withdrawn_rub": str(withdrawn),
            "investment_pnl_rub": str(inv_pnl) if inv_pnl is not None else None,
            "realized_pnl_rub": str(money(portfolio.realized_pnl_rub or ZERO)),
            "valuation_complete": valuation_complete,
            "valuation_partial": not valuation_complete,
            "valuation_as_of": as_of_to,
            "valuation_from": as_of_from,
            "valuation_to": as_of_to,
            "valuation_label": _valuation_label(
                price_dates=price_dates, missing_prices=missing_prices
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
