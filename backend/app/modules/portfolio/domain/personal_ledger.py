"""Personal Portfolio V1 ledger math (Decimal only).

Accounting method: weighted-average cost.
Commission on BUY/SELL is included in that trade's cash impact and
(for BUY) in cost basis. Separate COMMISSION events reduce cash only —
never apply both for the same fee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

MONEY = Decimal("0.000001")
UNITS = Decimal("0.00000001")
ZERO = Decimal("0")


class OperationType(StrEnum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY = "BUY"
    SELL = "SELL"
    COMMISSION = "COMMISSION"
    OPENING_CASH = "OPENING_CASH"
    OPENING_POSITION = "OPENING_POSITION"
    DIVIDEND = "DIVIDEND"
    COUPON = "COUPON"
    TAX = "TAX"
    AMORTIZATION = "AMORTIZATION"
    OTHER_FEE = "OTHER_FEE"


class LedgerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _d(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value: object) -> Decimal:
    return _d(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def units_q(value: object) -> Decimal:
    return _d(value).quantize(UNITS, rounding=ROUND_HALF_UP)


@dataclass
class PositionBook:
    units: Decimal = ZERO
    average_cost: Decimal | None = None  # per unit RUB; None = unknown basis


@dataclass
class LedgerState:
    cash: Decimal = ZERO
    contributed: Decimal = ZERO
    withdrawn: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    positions: dict[int, PositionBook] = field(default_factory=dict)
    cost_basis_incomplete: bool = False

    def clone(self) -> LedgerState:
        return LedgerState(
            cash=self.cash,
            contributed=self.contributed,
            withdrawn=self.withdrawn,
            realized_pnl=self.realized_pnl,
            positions={
                iid: PositionBook(units=p.units, average_cost=p.average_cost)
                for iid, p in self.positions.items()
            },
            cost_basis_incomplete=self.cost_basis_incomplete,
        )


@dataclass(frozen=True)
class LedgerEvent:
    operation_type: OperationType
    instrument_id: int | None = None
    units: Decimal = ZERO
    price: Decimal | None = ZERO
    amount: Decimal = ZERO
    commission: Decimal = ZERO


def apply_event(state: LedgerState, event: LedgerEvent) -> LedgerState:
    """Return a new state after applying one ACTIVE journal event."""
    out = state.clone()
    op = event.operation_type
    commission = money(event.commission)
    if commission < ZERO:
        raise LedgerError("INVALID_COMMISSION", "Комиссия не может быть отрицательной")

    if op in (OperationType.DEPOSIT, OperationType.OPENING_CASH):
        amount = money(event.amount)
        if amount <= ZERO:
            raise LedgerError("INVALID_AMOUNT", "Сумма пополнения должна быть больше нуля")
        out.cash = money(out.cash + amount)
        out.contributed = money(out.contributed + amount)
        return out

    if op == OperationType.WITHDRAWAL:
        amount = money(event.amount)
        if amount <= ZERO:
            raise LedgerError("INVALID_AMOUNT", "Сумма вывода должна быть больше нуля")
        if out.cash < amount:
            raise LedgerError("INSUFFICIENT_CASH", "Недостаточно свободных денег")
        out.cash = money(out.cash - amount)
        out.withdrawn = money(out.withdrawn + amount)
        return out

    if op == OperationType.COMMISSION:
        fee = money(event.amount if event.amount else event.commission)
        if fee <= ZERO:
            raise LedgerError("INVALID_AMOUNT", "Сумма комиссии должна быть больше нуля")
        if out.cash < fee:
            raise LedgerError("INSUFFICIENT_CASH", "Недостаточно свободных денег")
        out.cash = money(out.cash - fee)
        return out

    if op in (OperationType.TAX, OperationType.OTHER_FEE):
        fee = money(event.amount)
        if fee <= ZERO:
            raise LedgerError("INVALID_AMOUNT", "Сумма должна быть больше нуля")
        if out.cash < fee:
            raise LedgerError("INSUFFICIENT_CASH", "Недостаточно свободных денег")
        out.cash = money(out.cash - fee)
        return out

    if op in (OperationType.DIVIDEND, OperationType.COUPON, OperationType.AMORTIZATION):
        amount = money(event.amount)
        if amount <= ZERO:
            raise LedgerError("INVALID_AMOUNT", "Сумма должна быть больше нуля")
        out.cash = money(out.cash + amount)
        return out

    if op == OperationType.OPENING_POSITION:
        if event.instrument_id is None:
            raise LedgerError("INSTRUMENT_REQUIRED", "Нужно указать инструмент")
        u = units_q(event.units)
        if u <= ZERO:
            raise LedgerError("INVALID_UNITS", "Количество бумаг должно быть больше нуля")
        cost_known = event.price is not None
        px = money(event.price) if cost_known else None
        if cost_known and px is not None and px < ZERO:
            raise LedgerError("INVALID_PRICE", "Цена не может быть отрицательной")
        book = out.positions.get(event.instrument_id) or PositionBook()
        if book.units > ZERO:
            if book.average_cost is None or px is None:
                # Any unknown side → keep units, mark basis unknown.
                book.units = units_q(book.units + u)
                book.average_cost = None
                out.cost_basis_incomplete = True
            else:
                total_cost = money(book.units * book.average_cost + u * px)
                new_units = units_q(book.units + u)
                book.average_cost = money(total_cost / new_units) if new_units > ZERO else None
                book.units = new_units
                out.contributed = money(out.contributed + money(u * px))
        else:
            book.units = u
            book.average_cost = px
            if px is None:
                out.cost_basis_incomplete = True
            else:
                out.contributed = money(out.contributed + money(u * px))
        out.positions[event.instrument_id] = book
        return out

    if op == OperationType.BUY:
        if event.instrument_id is None:
            raise LedgerError("INSTRUMENT_REQUIRED", "Нужно указать инструмент")
        u = units_q(event.units)
        if event.price is None:
            raise LedgerError("INVALID_PRICE", "Цена покупки должна быть больше нуля")
        px = money(event.price)
        if u <= ZERO:
            raise LedgerError("INVALID_UNITS", "Количество бумаг должно быть больше нуля")
        if px <= ZERO:
            raise LedgerError("INVALID_PRICE", "Цена покупки должна быть больше нуля")
        notional = money(u * px)
        cash_out = money(notional + commission)
        if out.cash < cash_out:
            raise LedgerError("INSUFFICIENT_CASH", "Недостаточно свободных денег")
        book = out.positions.get(event.instrument_id) or PositionBook()
        if book.average_cost is None and book.units > ZERO:
            # Mixing known BUY into unknown opening → basis stays incomplete.
            book.units = units_q(book.units + u)
            book.average_cost = None
            out.cost_basis_incomplete = True
        else:
            prior_cost = money((book.units * book.average_cost) if book.average_cost is not None else ZERO)
            total_cost = money(prior_cost + notional + commission)
            new_units = units_q(book.units + u)
            book.average_cost = money(total_cost / new_units)
            book.units = new_units
        out.positions[event.instrument_id] = book
        out.cash = money(out.cash - cash_out)
        return out

    if op == OperationType.SELL:
        if event.instrument_id is None:
            raise LedgerError("INSTRUMENT_REQUIRED", "Нужно указать инструмент")
        u = units_q(event.units)
        if event.price is None:
            raise LedgerError("INVALID_PRICE", "Цена продажи должна быть больше нуля")
        px = money(event.price)
        if u <= ZERO:
            raise LedgerError("INVALID_UNITS", "Количество бумаг должно быть больше нуля")
        if px <= ZERO:
            raise LedgerError("INVALID_PRICE", "Цена продажи должна быть больше нуля")
        book = out.positions.get(event.instrument_id)
        if book is None or book.units < u:
            raise LedgerError(
                "INSUFFICIENT_UNITS",
                "В портфеле недостаточно бумаг для этой продажи",
            )
        proceeds = money(money(u * px) - commission)
        if proceeds < ZERO:
            raise LedgerError("INVALID_COMMISSION", "Комиссия превышает сумму сделки")
        remaining = units_q(book.units - u)
        if book.average_cost is None:
            out.cost_basis_incomplete = True
            # Units/cash move; realized P&L not invented from unknown basis.
        else:
            cost = money(u * book.average_cost)
            realized = money(proceeds - cost)
            out.realized_pnl = money(out.realized_pnl + realized)
        if remaining == ZERO:
            del out.positions[event.instrument_id]
        else:
            book.units = remaining
            out.positions[event.instrument_id] = book
        out.cash = money(out.cash + proceeds)
        return out

    raise LedgerError("UNSUPPORTED_OPERATION", f"Операция {op} пока не поддерживается")


def investment_pnl(
    *,
    nav: Decimal,
    contributed: Decimal,
    withdrawn: Decimal,
) -> Decimal:
    """Absolute investment P&L excluding external cash flows."""
    net_external = money(contributed - withdrawn)
    return money(nav - net_external)


def lots_to_units(lots: Decimal, lot_size: int) -> Decimal:
    if lot_size <= 0:
        raise LedgerError("INVALID_LOT_SIZE", "Размер лота неизвестен или некорректен")
    return units_q(lots * Decimal(lot_size))
