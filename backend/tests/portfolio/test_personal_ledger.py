"""Pure Decimal ledger tests for Personal Portfolio V1."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.portfolio.domain.personal_ledger import (
    LedgerError,
    LedgerEvent,
    LedgerState,
    OperationType,
    apply_event,
    investment_pnl,
    money,
)


def test_deposit_then_extra_deposit_is_not_profit() -> None:
    s = LedgerState()
    s = apply_event(s, LedgerEvent(OperationType.DEPOSIT, amount=Decimal("100000")))
    assert s.cash == money("100000")
    nav = s.cash
    assert investment_pnl(nav=nav, contributed=s.contributed, withdrawn=s.withdrawn) == money("0")

    s = apply_event(s, LedgerEvent(OperationType.DEPOSIT, amount=Decimal("30000")))
    nav = s.cash
    assert nav == money("130000")
    assert investment_pnl(nav=nav, contributed=s.contributed, withdrawn=s.withdrawn) == money("0")


def test_buy_sell_commission_and_realized() -> None:
    s = LedgerState()
    s = apply_event(s, LedgerEvent(OperationType.DEPOSIT, amount=Decimal("100000")))
    s = apply_event(
        s,
        LedgerEvent(
            OperationType.BUY,
            instrument_id=1,
            units=Decimal("20"),
            price=Decimal("100"),
            commission=Decimal("50"),
        ),
    )
    # cash = 100000 - 2000 - 50
    assert s.cash == money("97950")
    assert s.positions[1].units == Decimal("20.00000000")
    assert s.positions[1].average_cost == money("102.5")  # (2000+50)/20

    s = apply_event(
        s,
        LedgerEvent(
            OperationType.SELL,
            instrument_id=1,
            units=Decimal("10"),
            price=Decimal("120"),
            commission=Decimal("10"),
        ),
    )
    # proceeds = 1200 - 10 = 1190; cost = 10*102.5 = 1025; realized = 165
    assert s.realized_pnl == money("165")
    assert s.positions[1].units == Decimal("10.00000000")
    assert s.positions[1].average_cost == money("102.5")


def test_separate_commission_once() -> None:
    s = LedgerState()
    s = apply_event(s, LedgerEvent(OperationType.DEPOSIT, amount=Decimal("1000")))
    s = apply_event(s, LedgerEvent(OperationType.COMMISSION, amount=Decimal("50")))
    assert s.cash == money("950")


def test_sell_beyond_holdings_rejected() -> None:
    s = LedgerState()
    s = apply_event(s, LedgerEvent(OperationType.DEPOSIT, amount=Decimal("100000")))
    s = apply_event(
        s,
        LedgerEvent(OperationType.BUY, instrument_id=1, units=Decimal("10"), price=Decimal("10")),
    )
    with pytest.raises(LedgerError) as ei:
        apply_event(
            s,
            LedgerEvent(OperationType.SELL, instrument_id=1, units=Decimal("11"), price=Decimal("10")),
        )
    assert ei.value.code == "INSUFFICIENT_UNITS"


def test_withdraw_beyond_cash_rejected() -> None:
    s = LedgerState()
    s = apply_event(s, LedgerEvent(OperationType.DEPOSIT, amount=Decimal("100")))
    with pytest.raises(LedgerError) as ei:
        apply_event(s, LedgerEvent(OperationType.WITHDRAWAL, amount=Decimal("101")))
    assert ei.value.code == "INSUFFICIENT_CASH"


def test_opening_position_counts_as_contribution_not_cash() -> None:
    s = LedgerState()
    s = apply_event(
        s,
        LedgerEvent(
            OperationType.OPENING_POSITION,
            instrument_id=7,
            units=Decimal("100"),
            price=Decimal("50"),
        ),
    )
    assert s.cash == money("0")
    assert s.contributed == money("5000")
    assert s.positions[7].average_cost == money("50")
