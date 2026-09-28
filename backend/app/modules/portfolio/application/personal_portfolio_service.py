"""Personal Portfolio V1 — journal apply, projection, valuation, reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
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
OPENING_SOURCE = "OPENING_SNAPSHOT"
JOURNAL_MANAGED_MESSAGE = (
    "Этот портфель уже ведёт историю операций. "
    "Добавьте покупку, продажу, пополнение или корректировку через «Добавить операцию»."
)
BOND_TRADE_MESSAGE = (
    "Kraken пока не умеет корректно учитывать новую сделку с облигацией. "
    "Текущую позицию можно хранить и анализировать."
)
OPENING_SYSTEM_ONLY_MESSAGE = "Начальное состояние создаётся Kraken при запуске учёта."
SYSTEM_ONLY_OPERATION_TYPES = frozenset(
    {OperationType.OPENING_CASH, OperationType.OPENING_POSITION}
)
LIFECYCLE_DRAFT = "DRAFT"
LIFECYCLE_ACTIVE = "ACTIVE"
MISSING_PRICE_MESSAGE = "Не хватает текущей цены для части позиций."
COST_BASIS_INCOMPLETE_MESSAGE = "Не хватает себестоимости для части позиций или истории."
INVESTMENT_PNL_MESSAGES = {
    "MISSING_PRICE": MISSING_PRICE_MESSAGE,
    "COST_BASIS_INCOMPLETE": COST_BASIS_INCOMPLETE_MESSAGE,
}


class PersonalPortfolioError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _d(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def get_or_create_primary(session: Session) -> ManualPortfolio:
    """REMOVED as product source of truth (Multi-Portfolio V2).

    Does **not** auto-create. Returns the oldest non-test book if one exists,
    otherwise raises ``PersonalPortfolioError(PORTFOLIO_NOT_FOUND)``.

    Prefer ``create_user_portfolio`` / ``get_portfolio``.
    """
    row = session.scalar(
        select(ManualPortfolio)
        .options(selectinload(ManualPortfolio.positions))
        .where(ManualPortfolio.is_test.is_(False))
        .order_by(ManualPortfolio.id.asc())
        .limit(1)
    )
    if row is not None:
        return row
    raise PersonalPortfolioError(
        "PORTFOLIO_NOT_FOUND",
        "Портфель не найден. Создайте портфель явно.",
        http_status=404,
    )


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
        status=LIFECYCLE_DRAFT,
        is_test=True,
        note="Isolated test portfolio — not the owner's real book",
        version=1,
    )
    session.add(row)
    session.flush()
    return row


def get_portfolio_for_update(
    session: Session,
    portfolio_id: int,
    *,
    allow_test: bool = False,
) -> ManualPortfolio:
    """Re-read the book by id with ``SELECT ... FOR UPDATE``.

    Every financial mutation must start here: the row lock serializes concurrent
    writers on the same book so the journal decision, idempotency check, ledger
    rebuild and projection all observe one consistent state. ``populate_existing``
    refreshes the identity-map instance — a stale ORM object must never drive a
    money decision.
    """
    row = session.scalar(
        select(ManualPortfolio)
        .where(ManualPortfolio.id == portfolio_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or (row.is_test and not allow_test):
        raise PersonalPortfolioError(
            "PORTFOLIO_NOT_FOUND",
            "Портфель не найден.",
            http_status=404,
        )
    return row


def lock_portfolio(session: Session, portfolio: ManualPortfolio) -> ManualPortfolio:
    """Row-lock an already-resolved book, preserving its test visibility."""
    return get_portfolio_for_update(
        session,
        int(portfolio.id),
        allow_test=bool(portfolio.is_test),
    )


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


def lifecycle_state(portfolio: ManualPortfolio) -> str:
    status = (portfolio.status or LIFECYCLE_DRAFT).upper()
    if status == LIFECYCLE_ACTIVE:
        return LIFECYCLE_ACTIVE
    return LIFECYCLE_DRAFT


def assert_legacy_writes_allowed(session: Session, portfolio: ManualPortfolio) -> None:
    if lifecycle_state(portfolio) == LIFECYCLE_ACTIVE or is_journal_managed(session, int(portfolio.id)):
        raise PersonalPortfolioError(
            "PORTFOLIO_NOT_DRAFT",
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
                price=_d(op.price) if op.price is not None else None,
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
    # Minute-level UTC — matches datetime-local operation entry.
    occurred_norm = occurred_at.astimezone(UTC).replace(second=0, microsecond=0).isoformat()
    return {
        "operation_type": operation_type,
        "occurred_at": occurred_norm,
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


def _has_legacy_snapshot(session: Session, portfolio: ManualPortfolio) -> bool:
    cash = money(portfolio.cash_rub)
    positions = _legacy_positions(session, int(portfolio.id))
    return cash != ZERO or len(positions) > 0


def journal_state(session: Session, portfolio: ManualPortfolio) -> str:
    """Product lifecycle for V2: DRAFT | ACTIVE.

    Legacy EMPTY / LEGACY_PENDING are mapped for older callers:
    - ACTIVE lifecycle → ACTIVE
    - DRAFT with no cash/positions → EMPTY (setup)
    - DRAFT with snapshot → DRAFT (ready to activate)
    """
    life = lifecycle_state(portfolio)
    if life == LIFECYCLE_ACTIVE or journal_operation_count(session, int(portfolio.id)) > 0:
        return LIFECYCLE_ACTIVE
    if _has_legacy_snapshot(session, portfolio):
        return LIFECYCLE_DRAFT
    return "EMPTY"


def journal_cutover_at(session: Session, portfolio_id: int) -> datetime | None:
    """Activation timestamp = MIN(occurred_at) of opening/bootstrap rows, if any."""
    return session.scalar(
        select(func.min(PersonalOperation.occurred_at)).where(
            PersonalOperation.portfolio_id == portfolio_id,
            PersonalOperation.source.in_([LEGACY_BOOTSTRAP_SOURCE, OPENING_SOURCE]),
        )
    )


def _fmt_cutover_human(ts: datetime) -> str:
    local = ts.astimezone(UTC)
    return local.strftime("%d.%m.%Y %H:%M UTC")


def activate_journal(session: Session, portfolio: ManualPortfolio) -> dict[str, Any]:
    """Activate DRAFT → ACTIVE via opening journal (Multi-Portfolio V2)."""
    from app.modules.portfolio.application.user_portfolio_service import activate_portfolio

    return activate_portfolio(session, portfolio)


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
    system: bool = False,
) -> PersonalOperation:
    """Append a journal operation.

    ``system=True`` is reserved for Kraken-internal writers (activation opening
    snapshot). Public callers must leave it ``False`` so opening rows can never be
    forged through the operations API.
    """
    portfolio = lock_portfolio(session, portfolio)
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

    if not system and op_type in SYSTEM_ONLY_OPERATION_TYPES:
        raise PersonalPortfolioError(
            "OPENING_OPERATION_SYSTEM_ONLY",
            OPENING_SYSTEM_ONLY_MESSAGE,
            http_status=409,
        )

    # Operations require ACTIVE lifecycle. Empty DRAFT may start with the first
    # journal operation (implicit empty activate) — a DRAFT with setup snapshot must
    # call activate explicitly.
    jstate = journal_state(session, portfolio)
    if jstate != LIFECYCLE_ACTIVE:
        if jstate == "EMPTY" and not _has_legacy_snapshot(session, portfolio):
            portfolio.status = LIFECYCLE_ACTIVE
            session.flush()
        else:
            raise PersonalPortfolioError(
                "PORTFOLIO_NOT_ACTIVE",
                "Сначала начните учёт для этого портфеля.",
                http_status=409,
            )

    occurred_dt = _parse_occurred_at(occurred_at)
    today = datetime.now(UTC).date()
    if occurred_dt.astimezone(UTC).date() > today:
        raise PersonalPortfolioError(
            "FUTURE_DATED_OPERATION",
            "Операцию нельзя датировать будущим днём — она сразу меняет текущее состояние портфеля.",
        )

    cutover = journal_cutover_at(session, int(portfolio.id))
    if cutover is not None and occurred_dt.astimezone(UTC) <= cutover.astimezone(UTC):
        raise PersonalPortfolioError(
            "OPERATION_BEFORE_JOURNAL_CUTOVER",
            (
                f"Этот портфель начал вести журнал с {_fmt_cutover_human(cutover)}. "
                "Более ранние операции уже входят в начальное состояние и не могут быть добавлены повторно."
            ),
            http_status=409,
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

    try:
        with session.begin_nested():
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


def _cancel_fingerprint(*, operation_id: int, reason: str | None) -> dict[str, Any]:
    return {
        "intent": "CANCEL",
        "operation_id": int(operation_id),
        "reason": (reason or "").strip() or None,
    }


def _cancel_fingerprint_from_marker(marker: PersonalOperation) -> dict[str, Any]:
    target = marker.supersedes_operation_id
    if target is None:
        return {"intent": "CANCEL", "operation_id": None, "reason": (marker.correction_reason or "").strip() or None}
    return _cancel_fingerprint(operation_id=int(target), reason=marker.correction_reason)


def cancel_operation(
    session: Session,
    *,
    portfolio: ManualPortfolio,
    operation_id: int,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> PersonalOperation:
    """Soft-cancel: mark CANCELLED and reproject. Returns original op. Atomic."""
    portfolio = lock_portfolio(session, portfolio)
    key = (idempotency_key or "").strip() or f"cancel:{operation_id}:{uuid4()}"
    expected = _cancel_fingerprint(operation_id=operation_id, reason=reason)
    existing = session.scalar(
        select(PersonalOperation).where(
            PersonalOperation.portfolio_id == portfolio.id,
            PersonalOperation.idempotency_key == key,
        )
    )
    if existing is not None:
        if _cancel_fingerprint_from_marker(existing) != expected:
            raise PersonalPortfolioError(
                "IDEMPOTENCY_KEY_REUSED",
                "Этот идентификатор операции уже использован для других данных.",
                http_status=409,
            )
        if existing.supersedes_operation_id is not None:
            original = session.get(PersonalOperation, existing.supersedes_operation_id)
            if original is not None:
                return original
        return existing

    try:
        with session.begin_nested():
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
            session.add(marker)
            session.flush()
            try:
                state = rebuild_ledger_from_journal(session, portfolio.id)
            except LedgerError as exc:
                # Dependent later journal would become invalid — full cancel mutation rolls back.
                raise PersonalPortfolioError(exc.code, exc.message, http_status=409) from exc
            project_portfolio(session, portfolio, state)
            return op
    except IntegrityError as exc:
        raced = session.scalar(
            select(PersonalOperation).where(
                PersonalOperation.portfolio_id == portfolio.id,
                PersonalOperation.idempotency_key == key,
            )
        )
        if raced is None:
            raise
        if _cancel_fingerprint_from_marker(raced) != expected:
            raise PersonalPortfolioError(
                "IDEMPOTENCY_KEY_REUSED",
                "Этот идентификатор операции уже использован для других данных.",
                http_status=409,
            ) from exc
        if raced.supersedes_operation_id is not None:
            original = session.get(PersonalOperation, raced.supersedes_operation_id)
            if original is not None:
                return original
        return raced


def reconcile(session: Session, portfolio: ManualPortfolio) -> dict[str, Any]:
    state = rebuild_ledger_from_journal(session, portfolio.id)
    cash_ok = money(portfolio.cash_rub) == money(state.cash)
    contributed_ok = money(portfolio.total_contributed_rub or ZERO) == money(state.contributed)
    withdrawn_ok = money(portfolio.total_withdrawn_rub or ZERO) == money(state.withdrawn)
    realized_ok = money(portfolio.realized_pnl_rub or ZERO) == money(state.realized_pnl)

    projected = {
        int(p.instrument_id): (
            units_q(p.units),
            money(p.average_price) if p.average_price is not None else None,
        )
        for p in session.scalars(
            select(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id)
        ).all()
    }
    ledger_pos = {
        iid: (
            units_q(book.units),
            money(book.average_cost) if book.average_cost is not None else None,
        )
        for iid, book in state.positions.items()
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
            str(k): {
                "units": str(v[0]),
                "average_cost": str(v[1]) if v[1] is not None else None,
            }
            for k, v in ledger_pos.items()
        },
        "projected_positions": {
            str(k): {
                "units": str(v[0]),
                "average_cost": str(v[1]) if v[1] is not None else None,
            }
            for k, v in projected.items()
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


@dataclass
class PersonalPositionSnapshot:
    """One holding in the Personal Portfolio read model (downstream analytics input)."""

    position_id: int
    instrument_id: int
    symbol: str | None
    name: str | None
    asset_class: str | None
    units: Decimal
    average_cost_rub: Decimal | None
    cost_basis_usable: bool
    unit_price: Decimal | None
    market_value: Decimal | None
    price_date: str | None
    price_available: bool
    unrealized_pnl: Decimal | None
    lot_size: int | None = None
    lots: Decimal | None = None
    pnl_unavailable_reason: str | None = None


@dataclass
class PersonalPortfolioSnapshot:
    """Application read boundary for the real user book.

    Journal = authoritative history; ManualPortfolio/ManualPosition = projection;
    this snapshot = sole contract for Dashboard / Analysis / Relations / Compare / Rebalance.
    """

    portfolio: ManualPortfolio
    journal_state: str
    journal_cutover_at: datetime | None
    cash_rub: Decimal
    positions: list[PersonalPositionSnapshot] = field(default_factory=list)
    securities_value_rub: Decimal = ZERO
    known_nav_rub: Decimal = ZERO
    contributed_rub: Decimal = ZERO
    withdrawn_rub: Decimal = ZERO
    realized_pnl_rub: Decimal = ZERO
    investment_pnl_rub: Decimal | None = None
    valuation_complete: bool = True
    valuation_partial: bool = False
    valuation_as_of: str | None = None
    valuation_from: str | None = None
    valuation_to: str | None = None
    valuation_label: str | None = None
    missing_price_count: int = 0
    cost_basis_complete: bool = True
    cost_basis_incomplete_history: bool = False
    investment_pnl_unavailable_reason: str | None = None

    @property
    def symbols(self) -> list[str]:
        return [p.symbol for p in self.positions if p.symbol]


def load_personal_snapshot(
    session: Session,
    portfolio: ManualPortfolio | None = None,
) -> PersonalPortfolioSnapshot:
    """Load current Personal Portfolio state for downstream analytics.

    Requires an explicit portfolio for Multi-Portfolio V2. Passing None raises —
    there is no auto-primary.
    """
    if portfolio is None:
        raise PersonalPortfolioError(
            "PORTFOLIO_NOT_FOUND",
            "Портфель не указан.",
            http_status=404,
        )
    book = portfolio
    positions_out: list[PersonalPositionSnapshot] = []
    securities_mv = ZERO
    missing_prices = 0
    price_dates: list[str] = []
    cost_incomplete = False

    for pos in session.scalars(
        select(ManualPosition).where(ManualPosition.portfolio_id == book.id)
    ).all():
        instrument = session.get(Instrument, pos.instrument_id)
        if instrument is None:
            missing_prices += 1
            cost_incomplete = True
            positions_out.append(
                PersonalPositionSnapshot(
                    position_id=int(pos.id),
                    instrument_id=int(pos.instrument_id),
                    symbol=None,
                    name=None,
                    asset_class=None,
                    units=units_q(pos.units),
                    average_cost_rub=None,
                    cost_basis_usable=False,
                    unit_price=None,
                    market_value=None,
                    price_date=None,
                    price_available=False,
                    unrealized_pnl=None,
                    pnl_unavailable_reason="Инструмент не найден",
                )
            )
            continue

        asset = (instrument.asset_class or "").lower() or None
        lot_size = _resolve_lot_size(session, instrument)
        lots_display = None
        if lot_size and lot_size > 0:
            lots_display = units_q(pos.units) / Decimal(lot_size)
        unit_price, market_value, price_date, asset_hint = _personal_mark(
            session, instrument, _d(pos.units)
        )
        asset = asset_hint or asset
        unrealized = None
        # V2: average_price stores RUB per unit for equities/funds AND bonds (from total RUB).
        cost_usable = pos.average_price is not None
        average_cost = money(pos.average_price) if cost_usable else None
        if not cost_usable:
            cost_incomplete = True
        pnl_reason = None
        if not cost_usable:
            pnl_reason = "Себестоимость не указана — прибыль по этой позиции пока не рассчитывается."
        if unit_price is not None and market_value is not None:
            securities_mv = money(securities_mv + market_value)
            if price_date:
                price_dates.append(price_date)
            if cost_usable and average_cost is not None:
                unrealized = money(market_value - money(_d(pos.units) * average_cost))
        else:
            missing_prices += 1
        positions_out.append(
            PersonalPositionSnapshot(
                position_id=int(pos.id),
                instrument_id=int(instrument.id),
                symbol=instrument.symbol,
                name=instrument.name or instrument.symbol,
                asset_class=asset,
                units=units_q(pos.units),
                average_cost_rub=average_cost,
                cost_basis_usable=cost_usable,
                unit_price=money(unit_price) if unit_price is not None else None,
                market_value=money(market_value) if market_value is not None else None,
                price_date=price_date,
                price_available=unit_price is not None,
                unrealized_pnl=unrealized,
                lot_size=lot_size,
                lots=lots_display,
                pnl_unavailable_reason=pnl_reason,
            )
        )

    cash = money(book.cash_rub)
    contributed = money(book.total_contributed_rub or ZERO)
    withdrawn = money(book.total_withdrawn_rub or ZERO)
    journal_ops = journal_operation_count(session, int(book.id))
    # DRAFT before journal: provisional contribution = cash + known position costs
    # so investment P&L is not inflated by treating setup cash as profit.
    if lifecycle_state(book) == LIFECYCLE_DRAFT and journal_ops == 0:
        provisional = cash
        for p in positions_out:
            if p.cost_basis_usable and p.average_cost_rub is not None:
                provisional = money(provisional + money(p.units * p.average_cost_rub))
        contributed = provisional
        withdrawn = ZERO

    # History matters even when nothing unknown is held today: an unknown basis that
    # was already sold leaves `contributed` understated, so NAV − contributed would
    # report the missing cost as profit. The ledger flag is the only witness.
    history_incomplete = False
    if journal_ops > 0 or lifecycle_state(book) == LIFECYCLE_ACTIVE:
        try:
            history_incomplete = rebuild_ledger_from_journal(
                session, int(book.id)
            ).cost_basis_incomplete
        except LedgerError:
            history_incomplete = True
    cost_incomplete = cost_incomplete or history_incomplete

    valuation_complete = missing_prices == 0
    known_nav = money(cash + securities_mv)
    inv_pnl: Decimal | None
    inv_pnl_reason: str | None = None
    if cost_incomplete:
        inv_pnl_reason = "COST_BASIS_INCOMPLETE"
    elif not valuation_complete:
        inv_pnl_reason = "MISSING_PRICE"
    if inv_pnl_reason is None:
        inv_pnl = investment_pnl(nav=known_nav, contributed=contributed, withdrawn=withdrawn)
    else:
        inv_pnl = None
    as_of_from = min(price_dates) if price_dates else None
    as_of_to = max(price_dates) if price_dates else None
    valuation_as_of = as_of_to if valuation_complete and as_of_from is not None and as_of_from == as_of_to else None

    return PersonalPortfolioSnapshot(
        portfolio=book,
        journal_state=journal_state(session, book),
        journal_cutover_at=journal_cutover_at(session, int(book.id)),
        cash_rub=cash,
        positions=positions_out,
        securities_value_rub=securities_mv,
        known_nav_rub=known_nav,
        contributed_rub=contributed,
        withdrawn_rub=withdrawn,
        realized_pnl_rub=money(book.realized_pnl_rub or ZERO),
        investment_pnl_rub=inv_pnl,
        valuation_complete=valuation_complete,
        valuation_partial=not valuation_complete,
        valuation_as_of=valuation_as_of,
        valuation_from=as_of_from,
        valuation_to=as_of_to,
        valuation_label=_valuation_label(price_dates=price_dates, missing_prices=missing_prices),
        missing_price_count=missing_prices,
        cost_basis_complete=not cost_incomplete,
        cost_basis_incomplete_history=history_incomplete,
        investment_pnl_unavailable_reason=inv_pnl_reason,
    )


def get_personal_summary(session: Session, portfolio: ManualPortfolio, *, owner: bool = False) -> dict[str, Any]:
    snap = load_personal_snapshot(session, portfolio)
    cost_complete = snap.cost_basis_complete
    pnl_reason = snap.investment_pnl_unavailable_reason
    pnl_message = INVESTMENT_PNL_MESSAGES.get(pnl_reason or "")
    positions_out: list[dict[str, Any]] = []
    for p in snap.positions:
        cost_total = None
        if p.average_cost_rub is not None:
            cost_total = money(p.units * p.average_cost_rub)
        positions_out.append(
            {
                "id": p.position_id,
                "instrument_id": p.instrument_id,
                "secid": p.symbol,
                "name": p.name,
                "asset_class": p.asset_class,
                "units": str(p.units),
                "lots": str(p.lots) if p.lots is not None else None,
                "lot_size": p.lot_size,
                "average_price": str(p.average_cost_rub) if p.average_cost_rub is not None else None,
                "cost_basis_total_rub": str(cost_total) if cost_total is not None else None,
                "cost_basis_status": "KNOWN" if p.cost_basis_usable else "UNKNOWN",
                "current_price": str(p.unit_price) if p.unit_price is not None else None,
                "price_date": p.price_date,
                "market_value": str(p.market_value) if p.market_value is not None else None,
                "unrealized_pnl": str(p.unrealized_pnl) if p.unrealized_pnl is not None else None,
                "price_available": p.price_available,
                "price_label": None if p.price_available else "Цена недоступна",
                "pnl_unavailable_reason": p.pnl_unavailable_reason,
            }
        )

    ops = list(
        session.scalars(
            select(PersonalOperation)
            .where(PersonalOperation.portfolio_id == snap.portfolio.id)
            .order_by(PersonalOperation.occurred_at.desc(), PersonalOperation.id.desc())
            .limit(50)
        ).all()
    )
    has_ops = journal_operation_count(session, int(snap.portfolio.id)) > 0
    cutover = snap.journal_cutover_at
    life = lifecycle_state(snap.portfolio)

    payload: dict[str, Any] = {
        "portfolio": {
            "id": snap.portfolio.id,
            "name": snap.portfolio.name,
            "description": snap.portfolio.note,
            "base_currency": snap.portfolio.base_currency,
            "lifecycle_state": life,
            "status": snap.portfolio.status,
            "is_test": bool(snap.portfolio.is_test),
            "note": snap.portfolio.note,
            "version": snap.portfolio.version,
            "has_operations": has_ops,
            "journal_state": snap.journal_state,
            "journal_cutover_at": cutover.isoformat() if cutover else None,
            "created_at": snap.portfolio.created_at.isoformat() if snap.portfolio.created_at else None,
            "updated_at": snap.portfolio.updated_at.isoformat() if snap.portfolio.updated_at else None,
        },
        "summary": {
            "cash_rub": str(snap.cash_rub),
            "securities_value_rub": str(snap.securities_value_rub),
            "nav_rub": str(snap.known_nav_rub),
            "known_nav_rub": str(snap.known_nav_rub),
            "contributed_rub": str(snap.contributed_rub),
            "withdrawn_rub": str(snap.withdrawn_rub),
            "investment_pnl_rub": (
                str(snap.investment_pnl_rub) if snap.investment_pnl_rub is not None else None
            ),
            "realized_pnl_rub": str(snap.realized_pnl_rub),
            "cost_basis_complete": cost_complete,
            "cost_basis_incomplete_reason": (
                None if cost_complete else COST_BASIS_INCOMPLETE_MESSAGE
            ),
            "cost_basis_incomplete_history": snap.cost_basis_incomplete_history,
            "investment_pnl_unavailable_reason": pnl_reason,
            "investment_pnl_message": pnl_message,
            "valuation_complete": snap.valuation_complete,
            "valuation_partial": snap.valuation_partial,
            "valuation_as_of": snap.valuation_as_of,
            "valuation_from": snap.valuation_from,
            "valuation_to": snap.valuation_to,
            "valuation_label": snap.valuation_label,
            "missing_price_count": snap.missing_price_count,
        },
        "positions": positions_out,
        "operations": [_operation_to_dict(o, owner=owner) for o in ops],
        "recommendation_disclaimer": "Модельная рекомендация",
    }
    if owner:
        payload["reconciliation"] = reconcile(session, snap.portfolio)
    return payload
